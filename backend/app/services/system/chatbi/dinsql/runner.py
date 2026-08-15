"""DIN-SQL flow adapted to ChatBI benchmark datasources."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
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
from .prompts import (
    CLASSIFICATION_PROMPT,
    HARD_PROMPT,
    MEDIUM_PROMPT,
    SCHEMA_LINKING_PROMPT,
)


@dataclass(slots=True)
class DinSqlRunResult:
    sql: str
    stage_latency_ms: dict[str, int]
    token_usage: dict[str, int | None]
    raw_output: dict[str, Any]
    query_stream_events: list[dict[str, Any]]


@dataclass(slots=True)
class _DinSqlSchemaText:
    fields: str
    foreign_keys: str
    primary_keys: str


@dataclass(slots=True)
class _DinSqlCallResult:
    responses: list[str]
    usage: dict[str, int] = field(default_factory=dict)


class DinSqlRunner:
    """Run the original DIN-SQL four-step prompt flow against a ChatBI datasource."""

    def __init__(self, *, llm_service: LLMService) -> None:
        self._llm = llm_service

    async def run(
        self,
        *,
        question: str,
        datasource: ChatbiDatasourceRecord,
        model: str | None,
        temperature: float = 0,
        n: int = 1,
    ) -> DinSqlRunResult:
        """Sync-style wrapper: collect all events and return the final result."""
        query_stream_events: list[dict[str, Any]] = []
        result = None
        async for event in self.run_stream(
            question=question,
            datasource=datasource,
            model=model,
            temperature=temperature,
            n=n,
        ):
            query_stream_events.append(event)
            if event.event == CHATBI_SSE_SQL and event.sql:
                result = event.sql
            if event.event == CHATBI_SSE_COMPLETED:
                break
        return DinSqlRunResult(
            sql=result or "",
            stage_latency_ms={},
            token_usage={},
            raw_output={},
            query_stream_events=query_stream_events,
        )

    async def run_stream(
        self,
        *,
        question: str,
        datasource: ChatbiDatasourceRecord,
        model: str | None,
        temperature: float = 0,
        n: int = 1,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        if datasource.db_schema is None:
            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_FAILED,
                text="DIN-SQL requires datasource db_schema",
            )
            return

        schema = ChatbiDbSchemaRecord.from_json_dict(datasource.db_schema)
        schema_text = _build_dinsql_schema_text(schema)
        timings: dict[str, int] = {}
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        debugged_sql = ""

        yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="DIN-SQL schema linking")

        schema_prompt = _schema_linking_prompt_maker(question, schema_text)
        schema_call, elapsed = await self._call_generation(
            prompt=schema_prompt,
            model=model,
            n=1,
            temperature=0,
            stop=["Q:"],
        )
        timings["schema_linking"] = elapsed
        _add_usage(usage_total, schema_call.usage)
        schema_linking_output = _first_response(schema_call)
        schema_links = _parse_schema_links(schema_linking_output)

        yield ChatbiQueryStreamEvent(
            event="schema_linking",
            text=schema_linking_output,
            schema_fields=[schema_links] if schema_links and schema_links != "[]" else [],
        )

        yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="DIN-SQL classification")

        classification_prompt = _classification_prompt_maker(
            question,
            schema_links[1:],
            schema_text,
        )
        classification_call, elapsed = await self._call_generation(
            prompt=classification_prompt,
            model=model,
            n=1,
            temperature=0,
            stop=["Q:"],
        )
        timings["classification"] = elapsed
        _add_usage(usage_total, classification_call.usage)
        classification_output = _first_response(classification_call)
        sub_questions, flag = _parse_classification(classification_output)

        yield ChatbiQueryStreamEvent(
            event="classification",
            text=f"{classification_output}\nflag: {flag}",
        )

        yield ChatbiQueryStreamEvent(
            event=CHATBI_SSE_STARTED,
            text=f"DIN-SQL SQL generation (flag={flag})",
        )

        if flag == "NESTED":
            sql_prompt = _hard_prompt_maker(
                question=question,
                schema_links=schema_links,
                sub_questions=sub_questions,
                schema_text=schema_text,
            )
        else:
            sql_prompt = _medium_prompt_maker(
                question=question,
                schema_links=schema_links,
                schema_text=schema_text,
            )
        sql_call, elapsed = await self._call_generation(
            prompt=sql_prompt,
            model=model,
            n=n,
            temperature=temperature,
            stop=["Q:"],
        )
        timings["sql_generation"] = elapsed
        _add_usage(usage_total, sql_call.usage)
        generated_sql_candidates = [_parse_generated_sql(item) for item in sql_call.responses]

        yield ChatbiQueryStreamEvent(
            event=CHATBI_SSE_SQL_CANDIDATES,
            sql_candidates=[{"sql": s} for s in generated_sql_candidates],
        )

        yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, text="DIN-SQL debug")

        debug_outputs: list[str] = []
        debug_usages: list[dict[str, int]] = []
        for sql in generated_sql_candidates[:1]:
            debug_prompt = _debug_prompt_maker(question, sql, schema_text)
            debug_call, elapsed = await self._call_debug(
                prompt=debug_prompt,
                model=model,
                n=1,
                temperature=0,
            )
            timings["sql_debug"] = elapsed
            _add_usage(usage_total, debug_call.usage)
            debug_usages.append(debug_call.usage)
            debugged_sql = _normalize_debugged_sql(_first_response(debug_call))
            debug_outputs.append(debugged_sql)

        yield ChatbiQueryStreamEvent(
            event=CHATBI_SSE_SQL,
            sql=debugged_sql,
        )

        yield ChatbiQueryStreamEvent(
            event=CHATBI_SSE_COMPLETED,
            sql=debugged_sql,
            total_tokens=usage_total.get("total_tokens"),
        )

    async def _call_generation(
        self,
        *,
        prompt: str,
        model: str | None,
        n: int,
        temperature: float,
        stop: list[str],
    ) -> tuple[_DinSqlCallResult, int]:
        return await self._completion(
            prompt=prompt,
            model=model,
            n=n,
            temperature=temperature,
            max_tokens=1000,
            stop=stop,
        )

    async def _call_debug(
        self,
        *,
        prompt: str,
        model: str | None,
        n: int,
        temperature: float,
    ) -> tuple[_DinSqlCallResult, int]:
        return await self._completion(
            prompt=prompt,
            model=model,
            n=n,
            temperature=temperature,
            max_tokens=1000,
            stop=[";", "\n\n"],
        )

    async def _completion(
        self,
        *,
        prompt: str,
        model: str | None,
        n: int,
        temperature: float,
        max_tokens: int,
        stop: list[str],
    ) -> tuple[_DinSqlCallResult, int]:
        t0 = time.perf_counter()
        response = await self._llm.acompletion(
            CompletionRequest(
                model=_normalize_model(model),
                messages=[Message(role="user", content=prompt)],
                stream=False,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=1.0,
                stop=stop,
                provider_options={
                    "n": n,
                    "frequency_penalty": 0.0,
                    "presence_penalty": 0.0,
                },
            )
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        completion = cast(CompletionResponse, response)
        return (
            _DinSqlCallResult(
                responses=[str(choice.message.content or "") for choice in completion.choices],
                usage=_usage_dict(completion.usage),
            ),
            elapsed_ms,
        )


def _build_dinsql_schema_text(schema: ChatbiDbSchemaRecord) -> _DinSqlSchemaText:
    field_sections: list[str] = []
    foreign_keys: list[str] = []
    primary_keys: list[str] = []
    for table in schema.tables:
        columns = ["*"] + [column.name for column in table.columns]
        field_sections.append(f"Table {table.table_name}, columns = [{','.join(columns)}]")
        for column in table.columns:
            if any("PRIMARY KEY" in item.upper() for item in column.constraints):
                primary_keys.append(f"{table.table_name}.{column.name}")
        for fk in table.foreign_keys:
            foreign_keys.append(
                f"{table.table_name}.{fk.column} = "
                f"{fk.references.table}.{fk.references.column}"
            )
    return _DinSqlSchemaText(
        fields="\n".join(field_sections) + ("\n" if field_sections else ""),
        foreign_keys=f"[{','.join(foreign_keys)}]",
        primary_keys=f"[{','.join(primary_keys)}]",
    )


def _schema_linking_prompt_maker(question: str, schema_text: _DinSqlSchemaText) -> str:
    instruction = "# Find the schema_links for generating SQL queries for each question based on the database schema and Foreign keys.\n"
    return (
        instruction
        + SCHEMA_LINKING_PROMPT
        + schema_text.fields
        + "Foreign_keys = "
        + schema_text.foreign_keys
        + '\nQ: "'
        + question
        + """"\nA: Let鈥檚 think step by step."""
    )


def _classification_prompt_maker(
    question: str,
    schema_links: str,
    schema_text: _DinSqlSchemaText,
) -> str:
    instruction = '# For the given question, classify it as NESTED.\nAlways output Label: "NESTED".\n\n'
    return (
        instruction
        + schema_text.fields
        + "Foreign_keys = "
        + schema_text.foreign_keys
        + "\n"
        + CLASSIFICATION_PROMPT
        + 'Q: "'
        + question
        + "\nschema_links: "
        + schema_links
        + "\nA: Let鈥檚 think step by step."
    )


def _medium_prompt_maker(
    *,
    question: str,
    schema_links: str,
    schema_text: _DinSqlSchemaText,
) -> str:
    instruction = "# Use the schema links and Intermediate_representation to generate the SQL queries for each of the questions.\n"
    return (
        instruction
        + schema_text.fields
        + "Foreign_keys = "
        + schema_text.foreign_keys
        + "\n"
        + MEDIUM_PROMPT
        + 'Q: "'
        + question
        + "\nSchema_links: "
        + schema_links
        + "\nA: Let鈥檚 think step by step."
    )


def _hard_prompt_maker(
    *,
    question: str,
    schema_links: str,
    sub_questions: str,
    schema_text: _DinSqlSchemaText,
) -> str:
    instruction = "# Use the intermediate representation and the schema links to generate the SQL queries for each of the questions.\n"
    stepping = (
        f'\nA: Let\'s think step by step. "{question}" can be solved by knowing '
        f'the answer to the following sub-question "{sub_questions}".'
    )
    return (
        instruction
        + schema_text.fields
        + "Foreign_keys = "
        + schema_text.foreign_keys
        + "\n"
        + HARD_PROMPT
        + 'Q: "'
        + question
        + '"'
        + "\nschema_links: "
        + schema_links
        + stepping
        + '\nThe SQL query for the sub-question"'
    )


def _debug_prompt_maker(question: str, sql: str, schema_text: _DinSqlSchemaText) -> str:
    instruction = """#### For the given question, use the provided tables, columns, foreign keys, and primary keys to fix the given SQL QUERY for any issues. If there are any problems, fix them. If there are no issues, return the SQL QUERY as is. You should return the FIXED SQL QUERY only, without any explanation.
#### Use the following instructions for fixing the SQL QUERY:
1) Use the database values that are explicitly mentioned in the question.
2) Pay attention to the columns that are used for the JOIN by using the Foreign_keys.
3) Use DESC and DISTINCT when needed.
4) Pay attention to the columns that are used for the GROUP BY statement.
5) Pay attention to the columns that are used for the SELECT statement.
6) Only change the GROUP BY clause when necessary (Avoid redundant columns in GROUP BY).
7) Use GROUP BY on one column only.

"""
    return (
        instruction
        + schema_text.fields
        + "Foreign_keys = "
        + schema_text.foreign_keys
        + "\n"
        + "Primary_keys = "
        + schema_text.primary_keys
        + "\n"
        + "#### Question: "
        + question
        + "\n#### SQL QUERY\n"
        + sql
        + "\n#### FIXED SQL QUERY\nSELECT"
    )


def _parse_schema_links(output: str) -> str:
    try:
        return output.split("Schema_links: ", 1)[1]
    except IndexError:
        return "[]"


def _parse_classification(output: str) -> tuple[str, str]:
    try:
        sub_questions = output.split('questions = ["', 1)[1].split('"]', 1)[0]
        return sub_questions, "NESTED"
    except IndexError:
        return "", "NON-NESTED"


def _parse_generated_sql(output: str) -> str:
    try:
        sql = output.split("SQL:", 1)[1]
    except IndexError:
        sql = "SELECT"
    return _clean_sql(sql)


def _normalize_debugged_sql(output: str) -> str:
    sql = _clean_sql(output)
    if not sql:
        return "SELECT"
    if sql.lower().startswith(("select", "with")):
        return sql
    return f"SELECT {sql}".strip()


def _clean_sql(value: str) -> str:
    return (
        value.replace("\n", " ")
        .replace("```sql", "")
        .replace("```", "")
        .strip()
        .rstrip(";")
        .strip()
    )


def _first_response(call: _DinSqlCallResult) -> str:
    return call.responses[0] if call.responses else ""


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
