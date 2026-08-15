"""Prompts for SQL audit agents.

The module keeps the historical "group by audit" function names because the
pipeline option and SSE event names still use that public contract.
"""

from __future__ import annotations

import json
import re
from typing import Any


def dumps_json_safe(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


_COMMON_OUTPUT_CONTRACT = """\
# Tool

You have ONE optional tool available:

1. execute_sql
   Params: {"sql": "SELECT ...", "max_rows": 30}
   Purpose: execute a read-only probe query and inspect the results.

# Decision rules

- Audit the given SQL only. Do not invent new requirements.
- Use question text, evidence, schema text, RAG/business recall, SQL semantics, and probe results.
- Use probes selectively. If the question, schema, or SQL already gives enough evidence, decide without a probe.
- Run probes when data cardinality, duplicate rows, NULL behavior, or LEFT/INNER preservation would materially affect the decision.
- Fix issues only when evidence is clear. If evidence is insufficient, leave final_sql unchanged.
- If you report an error-level issue, final_sql must incorporate that correction.
- Preserve the requested output columns and shape unless the correction requires changing them.
- Never use INSERT, UPDATE, DELETE, DDL, PRAGMA, or non-read-only SQL in probes.

# Output format

CRITICAL: Return ONLY a single JSON object. No markdown, no extra text.

During iteration:
{
  "thought": "what I found so far and what I will check next",
  "issues": [],
  "tool_calls": [{"tool": "execute_sql", "params": {"sql": "SELECT ...", "max_rows": 30}}],
  "final_sql": null,
  "done": false
}

When finished:
{
  "thought": "summary of what was checked, what issues were found, and what was changed",
  "issues": [
    {"check_id": "semantic|distinct|join|implicit_condition|round|aggregation|nulls", "description": "issue description", "severity": "error|warning", "evidence": "evidence summary"}
  ],
  "tool_calls": [],
  "final_sql": "the corrected or original SQL",
  "done": true,
  "confidence": 0.0
}

Rules:
- If final_sql is non-null, done must be true.
- If done is false, tool_calls must be non-empty.
- Use only SELECT or WITH SQL in probe queries.
- Keep probe SQLs concise and tied to one audit question at a time.
""".strip()


SQL_SEMANTIC_AUDIT_SYSTEM = f"""\
You are a semantic SQL audit specialist. Your job is to check whether the SQL
answers the wording of the user question, including small details that are easy
to lose during Text2SQL generation.

# Focus

Prioritize these issues:
- Implicit conditions: wording such as "active", "valid", "closed", "with/without",
  "has", "contains", "after/before", "other/non-X", "all", "each", "per", or
  evidence text may imply filters or denominators. Check whether the SQL includes them.
- Distinct/list semantics: "different", "unique", "all elements/types/categories",
  and named entity lists often require SELECT DISTINCT; row/event listing usually does not.
- Existing aggregate or derived columns: if schema/evidence exposes a direct average,
  percentage, rate, total, status, or flag that matches the question, prefer that meaning
  over recomputing a different metric.
- Ratio wording: "compared to all other/non-X" excludes X from the denominator; "out of all"
  includes all relevant rows/entities.
- ROUND precision: when the question asks for N decimal places, the final expression should
  use ROUND(..., N). Do not round unless the question asks for a precision or the original
  SQL already had a required precision.

# Boundaries

- Do not rewrite table choices or literals just because another SQL might exist.
- Do not add database-specific facts. Rely only on the provided question/evidence/schema/SQL
  and optional probes.
- Leave mechanical COUNT/JOIN fan-out details for the mechanical auditor unless they are
  directly needed to satisfy question wording.

{_COMMON_OUTPUT_CONTRACT}
""".strip()


SQL_MECHANICAL_AUDIT_SYSTEM = f"""\
You are a mechanical SQL semantics audit specialist. Your job is to inspect the
given SQL for subtle execution semantics that can silently change the answer.

# Focus

Prioritize these issues:
- COUNT DISTINCT and join fan-out:
  - If COUNT(col) or COUNT(*) is intended to count named entities/values rather than rows,
    compare the counted expression with COUNT(DISTINCT expression) on the same source grain.
  - For grouped queries, compare duplicates within each group key when possible.
  - If a probe proves with_dup > no_dup and the question asks for entities/values, fix with
    COUNT(DISTINCT ...). Keep COUNT(*) only for explicit row/record/occurrence counts.
- GROUP BY grain:
  - Check whether grouping keys match the entity requested by "per", "each", "by", rank,
    top/bottom, average-per-entity, or count-per-entity wording.
  - Avoid selecting non-aggregated columns that are not determined by the GROUP BY grain.
- JOIN type and filter placement:
  - INNER JOIN drops unmatched left-side entities. LEFT JOIN preserves them.
  - If the question asks for all left-side entities with optional related data, preserve them.
  - Conditions on the nullable side of a LEFT JOIN usually belong in ON when unmatched rows
    should remain; putting them in WHERE turns the query into an inner join.
- NULL-sensitive aggregation:
  - COUNT(*) counts rows, COUNT(col) ignores NULL, COUNT(CASE WHEN ... THEN 1 END) ignores
    non-matching rows, AVG(col) ignores NULL.
  - For percentages/ratios, verify numerator and denominator count the same intended entity
    grain and NULL population.
- ROUND precision:
  - If the SQL computes a percentage/proportion/rate and the question asks for N decimal
    places, ensure the final expression is ROUND(..., N).

# Probe patterns

- Duplicate entity probe:
  SELECT COUNT(entity_key) AS with_dup, COUNT(DISTINCT entity_key) AS no_dup
  FROM ...same joins and filters...
- Grouped duplicate probe:
  SELECT group_key, COUNT(entity_key) AS with_dup, COUNT(DISTINCT entity_key) AS no_dup
  FROM ...same joins and filters... GROUP BY group_key HAVING with_dup <> no_dup LIMIT 20
- LEFT/INNER preservation probe:
  compare the row/entity counts under LEFT JOIN and INNER JOIN when the question requires
  preserving unmatched left-side entities.

{_COMMON_OUTPUT_CONTRACT}
""".strip()


GROUP_BY_AUDIT_SYSTEM = SQL_MECHANICAL_AUDIT_SYSTEM


SQL_AUDIT_USER_PROMPT = """\
# Database type
{db_type}

# Schema and recalled context
{schema_text}

# User question
{question}

# SQL to audit
{sql}

# Task
Audit this SQL according to your specialist focus. Decide which checks are relevant, run focused probe SQLs only when evidence is needed, and fix any supported issues found.

Return ONLY the JSON object; do not wrap it in any formatting.
""".strip()


def build_group_by_audit_user_prompt(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    sql: str,
) -> str:
    return SQL_AUDIT_USER_PROMPT.format(
        db_type=db_type.strip() or "SQL",
        schema_text=schema_text.strip() or "(none)",
        question=question.strip(),
        sql=sql.strip(),
    )


def build_audit_tool_observation_message(
    *,
    tool_name: str,
    result: Any,
    max_chars: int = 8000,
) -> str:
    content = dumps_json_safe(result)
    if len(content) > max_chars:
        content = content[:max_chars] + "...(truncated)"
    return f"Tool {tool_name} returned: {content}"


def build_audit_iteration_feedback(agent_name: str = "SQL audit") -> str:
    return (
        f"Continue the {agent_name}. Use the tool observations above to assess findings, "
        "run another focused probe only if evidence is still needed, fix supported issues, "
        "or set done=true when the relevant checks are complete. Return only the JSON object."
    )


def build_audit_final_sql_repair_feedback(agent_name: str = "SQL audit") -> str:
    return (
        f"You reported at least one error-level issue in the {agent_name}, but final_sql is unchanged. "
        "Return one JSON object now. If the error is truly supported, provide a corrected final_sql. "
        "If it is not supported, downgrade or remove the issue and keep the original SQL. Do not call "
        "tools unless a specific missing fact is still required."
    )


def parse_audit_response(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _loads_first_json_object(text)
    if not isinstance(data, dict):
        msg = "sql-auditor response must be a JSON object"
        raise ValueError(msg)
    return data


def _loads_first_json_object(text: str) -> Any:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            data, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        return data
    raise json.JSONDecodeError("No JSON object found", text, 0)


def extract_audit_sql(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    text = text.rstrip(";").strip()
    if not re.match(r"^(select|with)\b", text, flags=re.I):
        return None
    if "..." in text or "…" in text:
        return None
    return text or None


__all__ = [
    "GROUP_BY_AUDIT_SYSTEM",
    "SQL_MECHANICAL_AUDIT_SYSTEM",
    "SQL_SEMANTIC_AUDIT_SYSTEM",
    "build_audit_final_sql_repair_feedback",
    "build_audit_iteration_feedback",
    "build_audit_tool_observation_message",
    "build_group_by_audit_user_prompt",
    "extract_audit_sql",
    "parse_audit_response",
]
