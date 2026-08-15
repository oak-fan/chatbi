"""Independent single-agent iterative SQL runner for ChatBI."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast

from .....domain.system.chatbi.datasource import ChatbiDatasourceRecord
from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from .....domain.system.llm import CompletionRequest, CompletionResponse, Message, UsageInfo
from ...llm_service import LLMService
from ..benchmark import connector_type_to_dialect
from ..datasource.db_connection_service import ChatbiDbConnectionService
from ..multi_agent.prompts import build_schema_text
from ..multi_agent.tools import MultiAgentToolbox
from ..multi_agent.types import MultiAgentRunResult
from .prompts import (
    SINGLE_AGENT_SYSTEM,
    build_iteration_feedback_message,
    build_single_agent_user_prompt,
    build_tool_observation_message,
    extract_sql,
    parse_single_agent_response,
)
from .types import SingleAgentStep, SingleAgentToolCall


class SingleAgentSqlRunner:
    """Iteratively generate and verify a single SQL answer using agent-chosen tools."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        db_connection: ChatbiDbConnectionService,
        toolbox: MultiAgentToolbox | None = None,
        max_rounds: int = 5,
        timeout: int = 30,
    ) -> None:
        self._llm = llm_service
        self._db = db_connection
        self._toolbox = toolbox
        self._max_rounds = max(1, int(max_rounds))
        self._timeout = max(1, int(timeout))

    async def run(
        self,
        question: str,
        datasource: ChatbiDatasourceRecord,
        datasource_owner_id: int | None,
        model: str | None,
    ) -> MultiAgentRunResult:
        """Run the single-agent loop and return a benchmark-compatible result."""

        final_sql = ""
        confidence = 0.0
        events: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        token_usage: dict[str, int | None] = {}
        async for event in self.run_stream(
            question,
            datasource,
            datasource_owner_id,
            model,
        ):
            events.append(event)
            if event.get("type") == "thinking":
                steps.append(dict(event))
            elif event.get("type") == "tool_result":
                tool_results.append(dict(event))
            elif event.get("type") == "final":
                final_sql = str(event.get("sql") or "")
                confidence = float(event.get("confidence") or 0.0)
                token_usage = cast(dict[str, int | None], event.get("token_usage") or {})
        failed_events = [event for event in events if event.get("type") == "failed" or event.get("event") == "failed"]
        raw_output = {
            "confidence": confidence,
            "intermediate_steps": steps,
            "tool_results": tool_results,
            "events": events,
            "error": failed_events[-1].get("error") if failed_events else {},
        }
        return MultiAgentRunResult(
            sql=final_sql,
            candidates=[{"id": "single_agent_final", "sql": final_sql, "confidence": confidence}],
            agent_outputs={"single_agent": {"confidence": confidence, "steps": steps}},
            tool_results={"calls": tool_results},
            token_usage=token_usage,
            raw_output=raw_output,
            query_stream_events=events,
        )

    async def run_stream(
        self,
        question: str,
        datasource: ChatbiDatasourceRecord,
        datasource_owner_id: int | None,
        model: str | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream iterative thinking, tool calls, tool results, and final SQL events.

        All unexpected failures are converted to a failed SSE-style event so benchmark
        details can show the partial trace instead of losing the agent history.
        """

        try:
            async with asyncio.timeout(self._timeout):
                async for event in self._run_stream_body(
                    question=question,
                    datasource=datasource,
                    datasource_owner_id=datasource_owner_id,
                    model=model,
                ):
                    yield event
        except TimeoutError as exc:
            yield _failed_event(
                message=f"single-agent timed out after {self._timeout}s",
                exc=exc,
            )
        except Exception as exc:
            yield _failed_event(message="single-agent failed", exc=exc)

    async def _run_stream_body(
        self,
        *,
        question: str,
        datasource: ChatbiDatasourceRecord,
        datasource_owner_id: int | None,
        model: str | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if datasource.db_schema is None:
            raise ValueError("SINGLE_AGENT requires datasource db_schema")

        schema = ChatbiDbSchemaRecord.from_json_dict(datasource.db_schema)
        schema_text = build_schema_text(schema)
        db_type = connector_type_to_dialect(datasource.connector_type).upper()
        toolbox = self._toolbox or MultiAgentToolbox(
            llm_service=self._llm,
            db_connection=self._db,
            datasource_id=datasource.id,
            datasource_owner_id=datasource_owner_id,
            db_name=schema.database,
            db_type=db_type,
            schema=schema,
        )
        should_close_toolbox = self._toolbox is None
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        messages: list[Message] = [Message(role="system", content=SINGLE_AGENT_SYSTEM)]
        final_sql: str | None = None
        final_confidence = 0.0
        last_sql: str | None = None
        last_confidence = 0.0
        try:
            yield {"type": "round_start", "round": 0, "content": "initial knowledge_search"}
            initial_knowledge = await toolbox.knowledge_search(question, top_k=5)
            yield {
                "type": "tool_result",
                "tool": "knowledge_search",
                "result": _truncate_result(initial_knowledge),
            }
            messages.append(
                Message(
                    role="user",
                    content=build_single_agent_user_prompt(
                        question=question,
                        db_type=db_type,
                        schema_text=schema_text,
                        initial_knowledge=initial_knowledge,
                    ),
                )
            )

            for round_index in range(1, self._max_rounds + 1):
                yield {"type": "round_start", "round": round_index}
                parsed, raw_content, usage = await self._call_llm(messages=messages, model=model)
                _add_usage(total_usage, usage)
                thought = str(parsed.get("thought") or "").strip()
                current_sql = extract_sql(parsed.get("current_sql"))
                confidence = _coerce_confidence(parsed.get("confidence"))
                final_answer = bool(parsed.get("final_answer"))
                tool_calls = _parse_tool_calls(parsed.get("tool_calls"))
                step = SingleAgentStep(
                    round_index=round_index,
                    thought=thought,
                    current_sql=current_sql,
                    confidence=confidence,
                    final_answer=final_answer,
                    tool_calls=tool_calls,
                    raw_output=parsed,
                )
                if current_sql:
                    last_sql = current_sql
                    last_confidence = confidence
                    yield {
                        "type": "sql_update",
                        "round": round_index,
                        "sql": current_sql,
                        "confidence": confidence,
                    }
                yield {
                    "type": "thinking",
                    "round": round_index,
                    "content": thought,
                    "current_sql": current_sql,
                    "confidence": confidence,
                    "final_answer": final_answer,
                    "tool_calls": [
                        {"tool": call.tool, "params": call.params} for call in tool_calls
                    ],
                }

                assistant_payload = dict(parsed)
                assistant_payload.pop("tool_calls", None)
                messages.append(
                    Message(
                        role="assistant",
                        content=_json_dumps(assistant_payload),
                    )
                )

                if final_answer and current_sql:
                    final_sql = current_sql
                    final_confidence = confidence
                    yield {
                        "type": "round_end",
                        "round": round_index,
                        "final_answer": True,
                    }
                    break

                for call in tool_calls:
                    yield {
                        "type": "tool_call",
                        "round": round_index,
                        "tool": call.tool,
                        "params": call.params,
                    }
                    result = await self._execute_tool_call(toolbox, call)
                    step.tool_results.append(result)
                    yield {
                        "type": "tool_result",
                        "round": round_index,
                        "tool": call.tool,
                        "result": _truncate_result(result),
                    }
                    messages.append(
                        Message(
                            role="assistant",
                            content=build_tool_observation_message(
                                tool_name=call.tool,
                                result=result,
                            ),
                        )
                    )
                messages.append(Message(role="user", content=build_iteration_feedback_message()))
                yield {"type": "round_end", "round": round_index, "final_answer": False}

            if final_sql is None and last_sql:
                final_sql = last_sql
                final_confidence = min(last_confidence, 0.5)
            if not final_sql:
                raise ValueError("single-agent did not produce SQL")
            yield {
                "type": "final",
                "sql": final_sql,
                "confidence": final_confidence,
                "token_usage": {k: v or None for k, v in total_usage.items()},
            }
        finally:
            if should_close_toolbox:
                await toolbox.close()

    async def _call_llm(
        self,
        *,
        messages: list[Message],
        model: str | None,
    ) -> tuple[dict[str, Any], str, dict[str, int]]:
        response = await self._llm.acompletion(
            CompletionRequest(
                model=_normalize_model(model),
                messages=messages,
                stream=False,
                temperature=0,
                max_tokens=1800,
                top_p=1.0,
            )
        )
        completion = cast(CompletionResponse, response)
        raw = str(completion.choices[0].message.content or "") if completion.choices else "{}"
        try:
            parsed = parse_single_agent_response(raw)
        except Exception as exc:
            repair_messages = [
                *messages,
                Message(role="assistant", content=raw),
                Message(
                    role="user",
                    content=(
                        "Your previous response was not valid JSON. Return exactly one JSON "
                        "object matching the required schema. Do not include Markdown."
                    ),
                ),
            ]
            repair = await self._llm.acompletion(
                CompletionRequest(
                    model=_normalize_model(model),
                    messages=repair_messages,
                    stream=False,
                    temperature=0,
                    max_tokens=1200,
                    top_p=1.0,
                )
            )
            repair_completion = cast(CompletionResponse, repair)
            raw = (
                str(repair_completion.choices[0].message.content or "")
                if repair_completion.choices
                else "{}"
            )
            try:
                parsed = parse_single_agent_response(raw)
            except Exception as repair_exc:
                raise ValueError(f"failed to parse single-agent JSON: {exc}") from repair_exc
        return parsed, raw, _usage_dict(completion.usage)

    async def _execute_tool_call(
        self,
        toolbox: MultiAgentToolbox,
        call: SingleAgentToolCall,
    ) -> dict[str, Any]:
        try:
            if call.tool == "knowledge_search":
                result = await toolbox.knowledge_search(
                    str(call.params.get("query") or ""),
                    top_k=int(call.params.get("top_k") or 5),
                )
            elif call.tool == "sql_probe":
                result = await toolbox.sql_probe(
                    str(call.params.get("sql") or ""),
                    mode=str(call.params.get("mode") or "query"),
                    max_rows=int(call.params.get("max_rows") or 30),
                )
            elif call.tool == "value_founding":
                result = await toolbox.value_founding(
                    table_name=str(call.params.get("table_name") or ""),
                    column_name=str(call.params.get("column_name") or ""),
                    literal=str(call.params.get("literal") or ""),
                    max_matches=int(call.params.get("max_matches") or 20),
                )
            else:
                return {
                    "tool": call.tool,
                    "params": call.params,
                    "success": False,
                    "error": f"unknown tool: {call.tool}",
                }
            return {
                "tool": call.tool,
                "params": call.params,
                "success": True,
                "result": result,
            }
        except Exception as exc:
            return {
                "tool": call.tool,
                "params": call.params,
                "success": False,
                "error": str(exc)[:2000],
            }


def _failed_event(*, message: str, exc: Exception) -> dict[str, Any]:
    return {
        "event": "failed",
        "type": "failed",
        "text": message,
        "error": {
            "message": message,
            "detail": str(exc)[:2000],
            "error_type": type(exc).__name__,
        },
    }


def _parse_tool_calls(value: Any) -> list[SingleAgentToolCall]:
    if not isinstance(value, list):
        return []
    calls: list[SingleAgentToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        params = item.get("params")
        if not tool:
            continue
        calls.append(
            SingleAgentToolCall(
                tool=tool,
                params=dict(params) if isinstance(params, dict) else {},
            )
        )
    return calls


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    return max(0.0, min(1.0, confidence))


def _usage_dict(usage: UsageInfo | None) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(usage.prompt_tokens or 0),
        "completion_tokens": int(usage.completion_tokens or 0),
        "total_tokens": int(usage.total_tokens or 0),
    }


def _add_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for key in total:
        total[key] += int(usage.get(key) or 0)


def _normalize_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    if not normalized or normalized == "default":
        return None
    return normalized


def _truncate_result(value: Any, *, max_chars: int = 6000) -> Any:
    text = _json_dumps(value)
    if len(text) <= max_chars:
        return value
    return {"truncated": True, "preview": text[:max_chars]}


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = ["SingleAgentSqlRunner"]
