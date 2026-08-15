"""GROUP BY auditor — ReAct iterative SQL probe agent."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

from .....domain.system.llm import CompletionRequest, CompletionResponse, Message, UsageInfo
from ...llm_service import LLMService
from .prompts import (
    SQL_MECHANICAL_AUDIT_SYSTEM,
    SQL_SEMANTIC_AUDIT_SYSTEM,
    build_audit_final_sql_repair_feedback,
    build_audit_iteration_feedback,
    build_audit_tool_observation_message,
    build_group_by_audit_user_prompt,
    extract_audit_sql,
    parse_audit_response,
)
from .types import AuditResult, AuditStep, AuditToolCall


class GroupByAuditorRunner:
    """Iteratively audit a SQL query with focused SQL audit specialists."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        execute_sql: Callable[[str, int], Any],
        max_rounds: int = 5,
        timeout: int = 20,
    ) -> None:
        """
        Args:
            llm_service: LLM completion service.
            execute_sql: async (sql, max_rows) -> (columns, rows, truncated).
            max_rounds: maximum number of LLM iterations.
            timeout: total timeout in seconds.
        """
        self._llm = llm_service
        self._exec_sql = execute_sql
        self._max_rounds = max(1, int(max_rounds))
        self._timeout = max(1, int(timeout))

    async def run(
        self,
        *,
        sql: str,
        question: str,
        db_type: str,
        schema_text: str,
        model: str | None = None,
    ) -> AuditResult:
        """Run the audit loop and return the result."""
        steps: list[dict[str, Any]] = []
        all_issues: list[dict[str, Any]] = []
        final_sql = sql
        confidence = 0.0

        async for event in self.run_stream(
            sql=sql,
            question=question,
            db_type=db_type,
            schema_text=schema_text,
            model=model,
        ):
            if event.get("type") == "thinking":
                steps.append(dict(event))
            elif event.get("type") == "final":
                final_sql = str(event.get("sql") or final_sql or sql)
                confidence = max(confidence, float(event.get("confidence") or 0.0))
                all_issues.extend(list(event.get("issues") or []))

        return AuditResult(
            original_sql=sql,
            final_sql=final_sql or sql,
            changed=(final_sql or sql) != sql,
            issues=all_issues,
            steps=steps,
            confidence=confidence,
        )

    async def run_stream(
        self,
        *,
        sql: str,
        question: str,
        db_type: str,
        schema_text: str,
        model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream per-round events from the audit loop."""
        current_sql = sql
        try:
            async with asyncio.timeout(self._timeout):
                for agent_name, system_prompt, max_rounds in self._audit_agents():
                    async for event in self._run_body(
                        sql=current_sql,
                        question=question,
                        db_type=db_type,
                        schema_text=schema_text,
                        model=model,
                        system_prompt=system_prompt,
                        agent_name=agent_name,
                        max_rounds=max_rounds,
                    ):
                        event["agent"] = agent_name
                        if event.get("type") == "final":
                            current_sql = str(event.get("sql") or current_sql or sql)
                        yield event
        except TimeoutError:
            yield {
                "type": "final",
                "agent": "audit_timeout",
                "sql": current_sql or sql,
                "thought": "SQL audit timed out; returning the latest audited SQL unchanged.",
                "issues": [],
                "confidence": 0.0,
            }
        except Exception:
            yield {
                "type": "final",
                "agent": "audit_error",
                "sql": current_sql or sql,
                "thought": "SQL audit failed; returning the latest audited SQL unchanged.",
                "issues": [],
                "confidence": 0.0,
            }

    def _audit_agents(self) -> tuple[tuple[str, str, int], ...]:
        semantic_rounds = max(1, min(2, self._max_rounds))
        mechanical_rounds = max(1, self._max_rounds - semantic_rounds)
        return (
            ("semantic_detail_audit", SQL_SEMANTIC_AUDIT_SYSTEM, semantic_rounds),
            ("mechanical_sql_audit", SQL_MECHANICAL_AUDIT_SYSTEM, mechanical_rounds),
        )

    async def _run_body(
        self,
        *,
        sql: str,
        question: str,
        db_type: str,
        schema_text: str,
        model: str | None,
        system_prompt: str,
        agent_name: str,
        max_rounds: int,
    ) -> AsyncIterator[dict[str, Any]]:
        messages: list[Message] = [
            Message(role="system", content=system_prompt),
            Message(
                role="user",
                content=build_group_by_audit_user_prompt(
                    question=question,
                    db_type=db_type,
                    schema_text=schema_text,
                    sql=sql,
                ),
            ),
        ]

        last_sql: str | None = None
        last_issues: list[dict[str, Any]] = []

        for round_index in range(1, max_rounds + 1):
            parsed, raw_content, usage = await self._call_llm(
                messages=messages, model=model,
            )

            thought = str(parsed.get("thought") or "").strip()
            issues = parsed.get("issues") if isinstance(parsed.get("issues"), list) else []
            tool_calls = _parse_tool_calls(parsed.get("tool_calls"))
            done = bool(parsed.get("done"))
            final_sql = extract_audit_sql(parsed.get("final_sql"))

            if final_sql:
                last_sql = final_sql
            if issues:
                last_issues = issues

            yield {
                "type": "thinking",
                "round": round_index,
                "agent": agent_name,
                "thought": thought,
                "issues": issues,
                "done": done,
                "final_sql": final_sql,
            }

            assistant_payload = dict(parsed)
            assistant_payload.pop("tool_calls", None)
            messages.append(
                Message(role="assistant", content=_json_dumps(assistant_payload)),
            )

            if done:
                if (
                    round_index < self._max_rounds
                    and _needs_final_sql_repair(
                        original_sql=sql,
                        final_sql=final_sql,
                        issues=issues,
                    )
                ):
                    messages.append(
                        Message(
                            role="user",
                            content=build_audit_final_sql_repair_feedback(agent_name),
                        )
                    )
                    continue
                yield {
                    "type": "final",
                    "agent": agent_name,
                    "sql": final_sql or sql,
                    "thought": thought,
                    "issues": issues,
                    "confidence": _coerce_confidence(parsed.get("confidence")),
                }
                return

            for call in tool_calls:
                yield {
                    "type": "tool_call",
                    "round": round_index,
                    "agent": agent_name,
                    "tool": call.tool,
                    "params": call.params,
                }
                result = await self._execute_tool_call(call)
                yield {
                    "type": "tool_result",
                    "round": round_index,
                    "agent": agent_name,
                    "tool": call.tool,
                    "result": _truncate(result),
                }
                messages.append(
                    Message(
                        role="assistant",
                        content=build_audit_tool_observation_message(
                            tool_name=call.tool, result=result,
                        ),
                    ),
                )

            messages.append(Message(role="user", content=build_audit_iteration_feedback(agent_name)))

        if last_sql:
            yield {
                "type": "final",
                "agent": agent_name,
                "sql": last_sql,
                "thought": "",
                "issues": last_issues,
                "confidence": min(0.5, 1.0),
            }
        else:
            yield {
                "type": "final",
                "agent": agent_name,
                "sql": sql,
                "thought": "",
                "issues": [],
                "confidence": 0.0,
            }

    async def _call_llm(
        self,
        *,
        messages: list[Message],
        model: str | None,
    ) -> tuple[dict[str, Any], str, dict[str, int]]:
        response: Any | None = None
        for attempt in range(2):
            try:
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
                break
            except Exception:
                if attempt >= 1:
                    raise
                await asyncio.sleep(5)
        completion = cast(CompletionResponse, response)
        raw = (
            str(completion.choices[0].message.content or "")
            if completion.choices
            else "{}"
        )
        try:
            parsed = parse_audit_response(raw)
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
                parsed = parse_audit_response(raw)
            except Exception as repair_exc:
                raise ValueError(
                    f"failed to parse group-by-auditor JSON: {exc}"
                ) from repair_exc
        return parsed, raw, _usage_dict(completion.usage)

    async def _execute_tool_call(self, call: AuditToolCall) -> dict[str, Any]:
        try:
            if call.tool == "execute_sql":
                probe_sql = str(call.params.get("sql") or "").strip()
                max_rows = int(call.params.get("max_rows") or 30)
                if not probe_sql:
                    return {"tool": "execute_sql", "success": False, "error": "empty sql"}
                columns, rows, truncated = await self._exec_sql(probe_sql, max_rows)
                return {
                    "tool": "execute_sql",
                    "sql": probe_sql,
                    "success": True,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "truncated": truncated,
                }
            return {
                "tool": call.tool,
                "success": False,
                "error": f"unknown tool: {call.tool}",
            }
        except Exception as exc:
            return {
                "tool": call.tool,
                "success": False,
                "error": str(exc)[:2000],
            }

def _needs_final_sql_repair(
    *,
    original_sql: str,
    final_sql: str | None,
    issues: list[Any],
) -> bool:
    if not final_sql or not _has_error_issue(issues):
        return False
    return _normalize_sql(final_sql) == _normalize_sql(original_sql)


def _has_error_issue(issues: list[Any]) -> bool:
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("severity") or "").strip().lower() == "error":
            return True
    return False


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.strip().rstrip(";").lower().split())


def _parse_tool_calls(value: Any) -> list[AuditToolCall]:
    if not isinstance(value, list):
        return []
    calls: list[AuditToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        params = item.get("params")
        if not tool:
            continue
        calls.append(
            AuditToolCall(
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


def _normalize_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    if not normalized or normalized == "default":
        return None
    return normalized


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _truncate(value: Any, *, max_chars: int = 6000) -> Any:
    text = _json_dumps(value)
    if len(text) <= max_chars:
        return value
    return {"truncated": True, "preview": text[:max_chars]}


__all__ = ["GroupByAuditorRunner"]





