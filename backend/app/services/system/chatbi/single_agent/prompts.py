"""Prompts for the independent ChatBI single-agent iterative SQL flow."""

from __future__ import annotations

import json
import re
from typing import Any

from ..query.prompts import dumps_json_safe


SINGLE_AGENT_SYSTEM = """
You are a senior Text-to-SQL agent and business analyst.

Your entire response must be a single valid JSON object. No extra text, no markdown code fences, no explanation. Only the JSON object.

Your task is to answer the user question with one high-quality SQL query. You do not generate
multiple candidates. Instead, you iteratively improve one SQL draft by calling tools, reading
their evidence, and revising the SQL.

# Available tools
1. knowledge_search
   Params:
   {"query": "business/schema question", "top_k": 5}
   Purpose: retrieve business meanings, field descriptions, value descriptions, and domain notes.

2. sql_probe
   Params:
   {"sql": "SELECT ...", "mode": "query|explain", "max_rows": 30}
   Purpose: execute read-only SQL or EXPLAIN to inspect values, distributions, NULLs, joins,
   grouping grain, row counts, and whether the SQL runs.

3. value_founding
   Params:
   {"table_name": "table", "column_name": "column", "literal": "text", "max_matches": 20}
   Purpose: find similar cell values in a specific column.

# Recommended workflow
1. Understand the question and schema.
2. Use initial knowledge hits, but do not over-trust them.
3. Draft SQL only after mapping required tables, columns, filters, joins, aggregation, and output grain.
4. Call tools whenever evidence is needed. Prefer sql_probe for concrete data facts.
5. Revise the SQL after tool observations.
6. Stop only when the SQL is supported by schema, business semantics, and data/tool evidence.

# Common pitfalls
- JOIN type: "each/every/all" may require preserving empty groups with LEFT JOIN.
- DISTINCT: entity counts usually need COUNT(DISTINCT entity_id) when joined to detail rows.
- NULL handling: decide whether NULL should be filtered, preserved, or COALESCE'd.
- Date boundaries: prefer half-open intervals for timestamp ranges.
- Cell values: verify spelling/casing/encoding using value_founding or sql_probe.
- Aggregation grain: GROUP BY stable keys, not only display names when names may duplicate.
- LEFT JOIN collapse: filters on the nullable side in WHERE can turn LEFT JOIN into INNER JOIN.
- LIMIT should normally have ORDER BY.

# Output format
**CRITICAL: The "current_sql" field must contain ONLY the raw SQL string, WITHOUT markdown code fences (```sql or ```). Do not wrap the SQL in backticks.**
Return exactly one JSON object with these fields:
{
  "thought": "brief reasoning summary, not a long hidden chain of thought",
  "current_sql": "",
  "tool_calls": [
    {"tool": "sql_probe", "params": {"sql": "SELECT ...", "mode": "query", "max_rows": 30}}
  ],
  "confidence": 0.0,
  "final_answer": false
}

Rules:
- Use only SELECT or WITH SQL.
- If final_answer is true, current_sql must be non-empty.
- If you are uncertain about literals, joins, DISTINCT, NULLs, or grouping, call tools before final_answer.
- Keep tool_calls empty only when no more evidence is needed.
- **Your response must be ONLY the JSON object, without any surrounding text, markdown, or commentary.**
""".strip()


SINGLE_AGENT_USER_PROMPT = """
# Database type
{db_type}

# Schema
{schema_text}

# User question
{question}

# Initial knowledge search hits
{initial_knowledge_json}

# Begin
Produce the first JSON response. You may include an initial SQL draft and tool calls for
evidence gathering. Use tools proactively before finalizing.

Return ONLY the JSON object; do not wrap it in any formatting, do not add extra text.
""".strip()


def build_single_agent_user_prompt(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    initial_knowledge: list[dict[str, Any]],
) -> str:
    """Build the first user message for the iterative single-agent runner."""

    return SINGLE_AGENT_USER_PROMPT.format(
        db_type=(db_type.strip() or "SQL"),
        schema_text=(schema_text.strip() or "(none)"),
        question=question.strip(),
        initial_knowledge_json=dumps_json_safe(initial_knowledge),
    )


def build_tool_observation_message(
    *,
    tool_name: str,
    result: Any,
    max_chars: int = 8000,
) -> str:
    """Render a tool result as a compact assistant message for the next round."""

    content = dumps_json_safe(result)
    if len(content) > max_chars:
        content = content[:max_chars] + "...(truncated)"
    return f"Tool {tool_name} returned: {content}"


def build_iteration_feedback_message() -> str:
    """Prompt the agent to continue after tool observations."""

    return (
        "Continue the iterative SQL generation. Use the tool observations above to revise "
        "current_sql, request more tools if needed, or set final_answer=true when confident. "
        "Return only the JSON object, with no extra text or markdown."
    )


def parse_single_agent_response(content: str) -> dict[str, Any]:
    """Parse the agent JSON response, tolerating fenced JSON or surrounding text."""

    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match is None:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        msg = "single-agent response must be a JSON object"
        raise ValueError(msg)
    return data


def extract_sql(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    
    # 处理多行Markdown代码块
    import re
    # 匹配 ```sql ... ``` 或 ``` ... ```
    pattern = r"```(?:sql)?\s*\n?(.*?)\n?```"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    
    # 如果整个字符串被反引号包围，移除它们
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    
    # 移除任何语言标识符如 "sql\n"
    if text.lower().startswith("sql\n"):
        text = text[4:].strip()
    
    text = text.rstrip(";").strip()
    return text or None


__all__ = [
    "SINGLE_AGENT_SYSTEM",
    "SINGLE_AGENT_USER_PROMPT",
    "build_iteration_feedback_message",
    "build_single_agent_user_prompt",
    "build_tool_observation_message",
    "extract_sql",
    "parse_single_agent_response",
]