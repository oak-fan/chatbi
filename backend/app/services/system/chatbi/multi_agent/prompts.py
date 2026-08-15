"""Prompts for the independent ChatBI multi-agent SQL flow."""

from __future__ import annotations

import json
import re
from typing import Any

from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from ..query.prompts import dumps_json_safe


SQL_GENERATOR_SYSTEM = """
You are the SQL candidate generator in a Text-to-SQL multi-agent workflow.

Generate 2 to 5 diverse SQL candidates for the user question. Keep the diversity controlled:
- explore JOIN type choices when the question may require preserving empty groups;
- explore DISTINCT / non-DISTINCT counting when entity duplication is plausible;
- explore aggregation grain, grouping columns, date boundary semantics, NULL handling, and value matching;
- use only real tables and columns from the schema;
- use SELECT / WITH only, no DDL or DML;
- follow the database dialect.

Every candidate must carry its own evidence and assumptions. Do not hide decisions.

Return exactly one JSON object:
{
  "candidates": [
    {
      "id": "c1",
      "sql": "SELECT ...",
      "assumptions": ["..."],
      "divergence_points": ["JOIN_TYPE", "DISTINCT_NECESSITY"],
      "evidence": [{"source": "schema|knowledge|question", "detail": "..."}]
    }
  ]
}
""".strip()


BUSINESS_AGENT_SYSTEM = """
You are the business understanding agent in a Text-to-SQL multi-agent workflow.

Your job is not to vote for a SQL blindly. Extract and verify business semantics:
- business metric definition;
- deduplication scope;
- whether computed fields are needed;
- date semantic ambiguity;
- literal/cell-value matching needs;
- implicit filters;
- aggregation level / grouping grain;
- DISTINCT necessity;
- NULL handling.

Use the provided knowledge-search hits, schema, and sample values as evidence. If evidence is weak,
state the uncertainty instead of inventing a rule.

Return exactly one JSON object:
{
  "constraints": {"metric": "...", "dedup_scope": "...", "grouping": "..."},
  "candidate_feedback": [{"candidate_id": "c1", "support": ["..."], "risks": ["..."]}],
  "evidence": [{"source": "knowledge|schema|value_founding|question", "detail": "..."}],
  "uncertainties": ["..."]
}
""".strip()


STRUCTURE_REVIEW_SYSTEM = """
You are the SQL structure review agent in a Text-to-SQL multi-agent workflow.

Review candidate SQLs for structural and semantic SQL risks:
- syntax and read-only safety;
- tables/columns that do not exist;
- unsupported JOIN paths;
- INNER vs LEFT JOIN mistakes;
- LEFT JOIN filters in WHERE that accidentally remove NULL-side rows;
- SELECT non-aggregate columns missing from GROUP BY;
- wrong aggregation grain;
- DISTINCT necessity;
- hidden NULL handling;
- date filters and LIMIT without ORDER BY.

Use schema and sql_probe results as evidence. Be skeptical but concise.

Return exactly one JSON object:
{
  "reviews": [
    {
      "candidate_id": "c1",
      "validity": "valid|risky|invalid",
      "risks": ["..."],
      "fix_suggestions": ["..."],
      "evidence": [{"source": "schema|sql_probe", "detail": "..."}]
    }
  ]
}
""".strip()


DATA_VALIDATION_SYSTEM = """
You are the data validation agent in a Text-to-SQL multi-agent workflow.

Use sql_probe previews and explain results to compare candidates empirically:
- whether the SQL executes;
- returned columns and row grain;
- row-count / NULL / DISTINCT clues;
- whether candidate differences are caused by JOIN type, DISTINCT, filters, grouping, or NULL handling;
- suspicious empty results.

Do not over-trust data previews; they are evidence, not ground truth.

Return exactly one JSON object:
{
  "comparisons": ["..."],
  "candidate_feedback": [{"candidate_id": "c1", "support": ["..."], "risks": ["..."]}],
  "evidence": [{"source": "sql_probe", "detail": "..."}]
}
""".strip()


JUDGE_SYSTEM = """
You are the final judge in a Text-to-SQL multi-agent workflow.

Choose the candidate SQL that best answers the question using all agents' evidence:
- question semantic coverage;
- business constraints;
- schema legality;
- SQL structure risks;
- data validation evidence;
- remaining uncertainty.

Execution success alone is not enough. Prefer the candidate with the best evidence closure.
If needed, you may output a corrected final SQL derived from the best candidate.

Return exactly one JSON object:
{
  "winner": "c1",
  "final_sql": "SELECT ...",
  "confidence": 0.0,
  "reason": "brief reason",
  "evidence": [{"source": "business_agent|structure_review|data_validation|schema", "detail": "..."}],
  "remaining_uncertainties": ["..."]
}
""".strip()



SQL_GENERATOR_USER_PROMPT = """
# Database type
{db_type}

# Schema
{schema_text}

# User question
{question}

# Knowledge search hits
{knowledge_hits_json}

# Task
Generate controlled-diversity SQL candidates. Each candidate must explicitly mark
assumptions, divergence_points, and evidence. Pay special attention to JOIN type,
DISTINCT, aggregation grain, date boundaries, NULL handling, and literal value matching.

[no prose][output json only]
""".strip()


BUSINESS_AGENT_USER_PROMPT = """
# Database type
{db_type}

# Schema
{schema_text}

# User question
{question}

# Knowledge search hits
{knowledge_hits_json}

# Candidate SQLs
{candidates_json}

# Task
Review business semantics for the question and candidates. Decide what can be supported by
knowledge/schema/question evidence, and mark uncertainty when evidence is insufficient.

[no prose][output json only]
""".strip()


STRUCTURE_REVIEW_USER_PROMPT = """
# Database type
{db_type}

# Schema
{schema_text}

# User question
{question}

# Business analysis
{business_analysis_json}

# Candidate SQLs
{candidates_json}

# SQL probe results
{sql_probe_results_json}

# Task
Review SQL structure and semantic SQL risks. Focus on executable syntax, real columns,
JOIN legality/type, LEFT JOIN filter collapse, GROUP BY correctness, DISTINCT, NULL handling,
date conditions, and LIMIT/ORDER BY.

[no prose][output json only]
""".strip()


DATA_VALIDATION_USER_PROMPT = """
# Database type
{db_type}

# Schema
{schema_text}

# User question
{question}

# Candidate SQLs
{candidates_json}

# SQL probe results
{sql_probe_results_json}

# Task
Compare candidates using execution previews and explain output. Identify what observed
differences suggest about JOIN type, DISTINCT, filters, grouping, NULL handling, row grain,
and suspicious empty results.

[no prose][output json only]
""".strip()


JUDGE_USER_PROMPT = """
# Database type
{db_type}

# Schema
{schema_text}

# User question
{question}

# Candidate SQLs
{candidates_json}

# Business analysis
{business_analysis_json}

# Structure review
{structure_review_json}

# Data validation
{data_validation_json}

# Tool results
{tool_results_json}

# Task
Choose or correct the final SQL using the evidence from all agents and tools. Explain the
decision briefly and list remaining uncertainties.

[no prose][output json only]
""".strip()


def build_schema_text(schema: ChatbiDbSchemaRecord) -> str:
    lines: list[str] = [f"database={schema.database}"]
    if schema.description:
        lines.append(f"description={schema.description}")
    for table in schema.tables:
        lines.append(f"table {table.table_name}:")
        for column in table.columns:
            attrs: list[str] = [f"type={column.type}"]
            if column.constraints:
                attrs.append(f"constraints={','.join(column.constraints)}")
            if column.comment:
                attrs.append(f"comment={column.comment}")
            if column.description:
                attrs.append(f"description={column.description}")
            if column.samples:
                attrs.append(f"samples={column.samples[:5]}")
            lines.append(f"- {column.name} ({'; '.join(attrs)})")
        if table.foreign_keys:
            lines.append("  foreign_keys:")
            for fk in table.foreign_keys:
                lines.append(
                    f"  - {table.table_name}.{fk.column} = "
                    f"{fk.references.table}.{fk.references.column}"
                )
    return "\n".join(lines)



def build_sql_generator_user_prompt(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    knowledge_hits: list[dict[str, Any]],
) -> str:
    return SQL_GENERATOR_USER_PROMPT.format(
        db_type=_clean_text(db_type, default="SQL"),
        schema_text=_clean_text(schema_text, default="(none)"),
        question=question.strip(),
        knowledge_hits_json=dumps_json_safe(knowledge_hits),
    )


def build_business_agent_user_prompt(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    knowledge_hits: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    return BUSINESS_AGENT_USER_PROMPT.format(
        db_type=_clean_text(db_type, default="SQL"),
        schema_text=_clean_text(schema_text, default="(none)"),
        question=question.strip(),
        knowledge_hits_json=dumps_json_safe(knowledge_hits),
        candidates_json=dumps_json_safe(candidates),
    )


def build_structure_review_user_prompt(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    business_analysis: dict[str, Any],
    candidates: list[dict[str, Any]],
    sql_probe_results: list[dict[str, Any]],
) -> str:
    return STRUCTURE_REVIEW_USER_PROMPT.format(
        db_type=_clean_text(db_type, default="SQL"),
        schema_text=_clean_text(schema_text, default="(none)"),
        question=question.strip(),
        business_analysis_json=dumps_json_safe(business_analysis),
        candidates_json=dumps_json_safe(candidates),
        sql_probe_results_json=dumps_json_safe(sql_probe_results),
    )


def build_data_validation_user_prompt(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    candidates: list[dict[str, Any]],
    sql_probe_results: list[dict[str, Any]],
) -> str:
    return DATA_VALIDATION_USER_PROMPT.format(
        db_type=_clean_text(db_type, default="SQL"),
        schema_text=_clean_text(schema_text, default="(none)"),
        question=question.strip(),
        candidates_json=dumps_json_safe(candidates),
        sql_probe_results_json=dumps_json_safe(sql_probe_results),
    )


def build_judge_user_prompt(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    candidates: list[dict[str, Any]],
    business_analysis: dict[str, Any],
    structure_review: dict[str, Any],
    data_validation: dict[str, Any],
    tool_results: dict[str, Any],
) -> str:
    return JUDGE_USER_PROMPT.format(
        db_type=_clean_text(db_type, default="SQL"),
        schema_text=_clean_text(schema_text, default="(none)"),
        question=question.strip(),
        candidates_json=dumps_json_safe(candidates),
        business_analysis_json=dumps_json_safe(business_analysis),
        structure_review_json=dumps_json_safe(structure_review),
        data_validation_json=dumps_json_safe(data_validation),
        tool_results_json=dumps_json_safe(tool_results),
    )


def build_agent_user_content(
    *,
    question: str,
    db_type: str,
    schema_text: str,
    payload: dict[str, Any] | None = None,
) -> str:
    parts = [
        "# Database type",
        db_type.strip() or "SQL",
        "",
        "# Schema",
        schema_text.strip() or "(none)",
        "",
        "# User question",
        question.strip(),
    ]
    if payload:
        parts.extend(["", "# Context", dumps_json_safe(payload)])
    parts.append("\n[no prose][output json only]")
    return "\n".join(parts)


def _clean_text(value: str, *, default: str) -> str:
    text = value.strip()
    return text or default


def parse_json_object(content: str) -> dict[str, Any]:
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
        msg = "agent response must be a JSON object"
        raise ValueError(msg)
    return data


def extract_sql(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text.rstrip(";").strip()


__all__ = [
    "build_structure_review_user_prompt",
    "build_sql_generator_user_prompt",
    "build_judge_user_prompt",
    "build_data_validation_user_prompt",
    "build_business_agent_user_prompt",
    "STRUCTURE_REVIEW_USER_PROMPT",
    "SQL_GENERATOR_USER_PROMPT",
    "JUDGE_USER_PROMPT",
    "DATA_VALIDATION_USER_PROMPT",
    "BUSINESS_AGENT_USER_PROMPT",
    "BUSINESS_AGENT_SYSTEM",
    "DATA_VALIDATION_SYSTEM",
    "JUDGE_SYSTEM",
    "SQL_GENERATOR_SYSTEM",
    "STRUCTURE_REVIEW_SYSTEM",
    "build_agent_user_content",
    "build_schema_text",
    "extract_sql",
    "parse_json_object",
]
