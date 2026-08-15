"""Independent ChatBI multi-agent SQL runner."""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, cast

from .....constants.chatbi.query import (
    CHATBI_SSE_COMPLETED,
    CHATBI_SSE_FAILED,
    CHATBI_SSE_SQL,
    CHATBI_SSE_SQL_CANDIDATES,
    CHATBI_SSE_STARTED,
)
from .....domain.system.chatbi.datasource import ChatbiDatasourceRecord
from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from .....domain.system.chatbi.query import ChatbiQueryStreamEvent
from .....domain.system.llm import CompletionRequest, CompletionResponse, Message, UsageInfo
from ...llm_service import LLMService
from ..benchmark import connector_type_to_dialect
from ..datasource.db_connection_service import ChatbiDbConnectionService
from .prompts import (
    BUSINESS_AGENT_SYSTEM,
    DATA_VALIDATION_SYSTEM,
    JUDGE_SYSTEM,
    SQL_GENERATOR_SYSTEM,
    STRUCTURE_REVIEW_SYSTEM,
    build_business_agent_user_prompt,
    build_data_validation_user_prompt,
    build_judge_user_prompt,
    build_sql_generator_user_prompt,
    build_structure_review_user_prompt,
    build_schema_text,
    extract_sql,
    parse_json_object,
)
from .tools import MultiAgentToolbox
from .types import AgentCallResult, MultiAgentRunResult


class MultiAgentSqlRunner:
    """Run SQL generation through independent evidence-producing agents."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        db_connection: ChatbiDbConnectionService,
    ) -> None:
        self._llm = llm_service
        self._db = db_connection

    async def run(
        self,
        *,
        question: str,
        datasource: ChatbiDatasourceRecord,
        datasource_owner_id: int | None,
        model: str | None,
    ) -> MultiAgentRunResult:
        events: list[dict[str, Any]] = []
        final_sql = ""
        token_usage: dict[str, int | None] = {}
        raw_output: dict[str, Any] = {}
        candidates: list[dict[str, Any]] = []
        async for event in self.run_stream(
            question=question,
            datasource=datasource,
            datasource_owner_id=datasource_owner_id,
            model=model,
        ):
            events.append(_event_payload(event))
            if event.event == CHATBI_SSE_SQL and event.sql:
                final_sql = event.sql
            if event.event == CHATBI_SSE_SQL_CANDIDATES:
                candidates = list(event.sql_candidates)
            if event.event == CHATBI_SSE_COMPLETED:
                token_usage = {"total_tokens": event.total_tokens} if event.total_tokens else {}
                raw_output = dict(event.validation or {})
        return MultiAgentRunResult(
            sql=final_sql,
            candidates=candidates,
            agent_outputs=raw_output.get("agent_outputs", {}),
            tool_results=raw_output.get("tool_results", {}),
            token_usage=token_usage,
            raw_output=raw_output,
            query_stream_events=events,
        )

    async def run_stream(
        self,
        *,
        question: str,
        datasource: ChatbiDatasourceRecord,
        datasource_owner_id: int | None,
        model: str | None,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        if datasource.db_schema is None:
            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_FAILED,
                text="MULTI_AGENT requires datasource db_schema",
            )
            return

        schema = ChatbiDbSchemaRecord.from_json_dict(datasource.db_schema)
        schema_text = build_schema_text(schema)
        db_type = connector_type_to_dialect(datasource.connector_type).upper()
        toolbox = MultiAgentToolbox(
            llm_service=self._llm,
            db_connection=self._db,
            datasource_id=datasource.id,
            datasource_owner_id=datasource_owner_id,
            db_name=schema.database,
            db_type=db_type,
            schema=schema,
        )
        agent_outputs: dict[str, Any] = {}
        tool_results: dict[str, Any] = {}
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        try:
            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="multi-agent knowledge search")
            knowledge_hits = await toolbox.knowledge_search(question, top_k=6)
            tool_results["knowledge_search"] = knowledge_hits

            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="multi-agent SQL generation")
            generator = await self._call_agent(
                name="sql_generator",
                system=SQL_GENERATOR_SYSTEM,
                user=build_sql_generator_user_prompt(
                    question=question,
                    db_type=db_type,
                    schema_text=schema_text,
                    knowledge_hits=knowledge_hits,
                ),
                model=model,
                temperature=0.4,
            )
            _add_usage(total_usage, generator.token_usage)
            candidates = _normalize_candidates(generator.output.get("candidates"))
            agent_outputs["sql_generator"] = generator.output
            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_SQL_CANDIDATES,
                sql_candidates=candidates,
            )

            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="multi-agent business review")
            business = await self._call_agent(
                name="business_agent",
                system=BUSINESS_AGENT_SYSTEM,
                user=build_business_agent_user_prompt(
                    question=question,
                    db_type=db_type,
                    schema_text=schema_text,
                    knowledge_hits=knowledge_hits,
                    candidates=candidates,
                ),
                model=model,
                temperature=0,
            )
            _add_usage(total_usage, business.token_usage)
            agent_outputs["business_agent"] = business.output

            probe_results = await self._probe_candidates(toolbox, candidates)
            tool_results["sql_probe"] = probe_results

            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="multi-agent structure review")
            structure = await self._call_agent(
                name="structure_review",
                system=STRUCTURE_REVIEW_SYSTEM,
                user=build_structure_review_user_prompt(
                    question=question,
                    db_type=db_type,
                    schema_text=schema_text,
                    business_analysis=business.output,
                    candidates=candidates,
                    sql_probe_results=probe_results,
                ),
                model=model,
                temperature=0,
            )
            _add_usage(total_usage, structure.token_usage)
            agent_outputs["structure_review"] = structure.output

            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="multi-agent data validation")
            data_validation = await self._call_agent(
                name="data_validation",
                system=DATA_VALIDATION_SYSTEM,
                user=build_data_validation_user_prompt(
                    question=question,
                    db_type=db_type,
                    schema_text=schema_text,
                    candidates=candidates,
                    sql_probe_results=probe_results,
                ),
                model=model,
                temperature=0,
            )
            _add_usage(total_usage, data_validation.token_usage)
            agent_outputs["data_validation"] = data_validation.output

            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="multi-agent judge")
            judge = await self._call_agent(
                name="judge",
                system=JUDGE_SYSTEM,
                user=build_judge_user_prompt(
                    question=question,
                    db_type=db_type,
                    schema_text=schema_text,
                    candidates=candidates,
                    business_analysis=business.output,
                    structure_review=structure.output,
                    data_validation=data_validation.output,
                    tool_results=tool_results,
                ),
                model=model,
                temperature=0,
            )
            _add_usage(total_usage, judge.token_usage)
            agent_outputs["judge"] = judge.output
            final_sql = extract_sql(str(judge.output.get("final_sql") or ""))
            if not final_sql:
                final_sql = _fallback_candidate_sql(candidates)

            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_SQL, sql=final_sql)
            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_COMPLETED,
                sql=final_sql,
                total_tokens=total_usage["total_tokens"] or None,
                validation={
                    "agent_outputs": agent_outputs,
                    "tool_results": tool_results,
                },
            )
        finally:
            await toolbox.close()

    async def _call_agent(
        self,
        *,
        name: str,
        system: str,
        user: str,
        model: str | None,
        temperature: float,
    ) -> AgentCallResult:
        t0 = time.perf_counter()
        response = await self._llm.acompletion(
            CompletionRequest(
                model=_normalize_model(model),
                messages=[
                    Message(role="system", content=system),
                    Message(role="user", content=user),
                ],
                stream=False,
                temperature=temperature,
                max_tokens=1800,
                top_p=1.0,
            )
        )
        del t0
        completion = cast(CompletionResponse, response)
        raw = str(completion.choices[0].message.content or "") if completion.choices else "{}"
        output = parse_json_object(raw)
        evidence = output.get("evidence")
        return AgentCallResult(
            name=name,
            output=output,
            raw_content=raw,
            evidence=evidence if isinstance(evidence, list) else [],
            token_usage=_usage_dict(completion.usage),
        )

    async def _probe_candidates(
        self,
        toolbox: MultiAgentToolbox,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "")
            sql = extract_sql(str(candidate.get("sql") or ""))
            if not candidate_id or not sql:
                continue
            query_result = await toolbox.sql_probe(sql, mode="query", max_rows=30)
            explain_result = await toolbox.sql_probe(sql, mode="explain", max_rows=30)
            results.append(
                {
                    "candidate_id": candidate_id,
                    "query": query_result,
                    "explain": explain_result,
                }
            )
        return results


def _normalize_candidates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("id") or f"c{idx}").strip()
        sql = extract_sql(str(item.get("sql") or ""))
        if not sql:
            continue
        if candidate_id in seen:
            candidate_id = f"c{idx}"
        seen.add(candidate_id)
        out.append(
            {
                "id": candidate_id,
                "sql": sql,
                "assumptions": item.get("assumptions") if isinstance(item.get("assumptions"), list) else [],
                "divergence_points": (
                    item.get("divergence_points")
                    if isinstance(item.get("divergence_points"), list)
                    else []
                ),
                "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
            }
        )
    return out


def _fallback_candidate_sql(candidates: list[dict[str, Any]]) -> str:
    for candidate in candidates:
        sql = extract_sql(str(candidate.get("sql") or ""))
        if sql:
            return sql
    return ""


def _usage_dict(usage: UsageInfo | None) -> dict[str, int]:
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(usage.prompt_tokens or 0),
        "completion_tokens": int(usage.completion_tokens or 0),
        "total_tokens": int(usage.total_tokens or 0),
    }


def _add_usage(total: dict[str, int], usage: dict[str, int | None]) -> None:
    for key in total:
        total[key] += int(usage.get(key) or 0)


def _normalize_model(model: str | None) -> str | None:
    if model is None:
        return None
    normalized = model.strip()
    if not normalized or normalized == "default":
        return None
    return normalized


def _event_payload(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    return {
        "event": event.event,
        "text": event.text,
        "sql": event.sql,
        "sql_candidates": event.sql_candidates,
        "validation": event.validation,
        "total_tokens": event.total_tokens,
        "error": event.error,
    }


__all__ = ["MultiAgentSqlRunner"]
