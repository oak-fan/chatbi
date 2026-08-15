"""Database value founding before Text2SQL generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Awaitable, Callable

from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord

try:  # pragma: no cover - exercised when optional dependency is installed.
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except ImportError:  # pragma: no cover - keeps local imports alive before poetry install.
    _rapidfuzz_fuzz = None


VALUE_FOUNDING_SYSTEM = """
# Role
You identify possible database cell values needed by a Text-to-SQL query.

# Definitions
- A literal value is a value stored inside database rows, not a schema/table/column name.
- Use the schema, column descriptions, and sample values to infer which columns may contain
  each literal.
- Include literals from the user question and Evidence when they are likely used in WHERE/JOIN
  filters, including names, addresses, enum labels, locations, dates, times, IDs, statuses,
  and domain phrases.

# Output requirement
Return exactly one JSON object, no Markdown and no extra prose:
{
  "literals": [
    {"value": "literal text from question/evidence", "columns": ["table.column"]}
  ]
}

# Few-shot example
Question:
What is the free or reduced price meal count for ages 5 to 17 in the Youth Authority School
with a mailing street address of PO Box 1040?

Output:
{
  "literals": [
    {
      "value": "PO Box 1040",
      "columns": ["schools.MailStreet", "schools.District"]
    },
    {
      "value": "Youth Authority School",
      "columns": ["schools.SOCType", "schools.School"]
    }
  ]
}
""".strip()

_COLUMN_REF_RE = re.compile(
    r"^\s*[`\"']?([A-Za-z_][\w\s$-]*)[`\"']?\s*\.\s*[`\"']?([^`\"'.]+)[`\"']?\s*$"
)


@dataclass(slots=True)
class ValueFoundingLiteral:
    value: str
    columns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValueFoundingMatch:
    literal: str
    column_ref: str
    value: str
    score: float


def build_value_founding_user_content(
    *,
    question: str,
    db_type: str,
    schema_text: str,
) -> str:
    return "\n".join(
        [
            "# Database type",
            db_type.strip() or "SQL",
            "",
            "# Schema with sample values",
            schema_text.strip() or "(none)",
            "",
            "# User question",
            question.strip(),
            "",
            "Identify possible database cell values and their possible table.column locations.",
            "[no prose][output json only]",
        ]
    )


def parse_value_founding_response(
    content: str,
    *,
    schema: ChatbiDbSchemaRecord,
    require_columns: bool = True,
) -> list[ValueFoundingLiteral]:
    data = _extract_json_object(content)
    raw_literals = data.get("literals")
    if not isinstance(raw_literals, list):
        return []
    valid_columns = _schema_column_refs(schema)
    out: list[ValueFoundingLiteral] = []
    seen_literals: set[tuple[str, tuple[str, ...]]] = set()
    for item in raw_literals:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        columns = _normalize_column_list(item.get("columns"), valid_columns=valid_columns)
        if require_columns and not columns:
            continue
        key = (value.casefold(), tuple(columns))
        if key in seen_literals:
            continue
        seen_literals.add(key)
        out.append(ValueFoundingLiteral(value=value, columns=columns))
    return out


def format_value_founding_matches_for_text2sql(matches: list[ValueFoundingMatch]) -> str | None:
    if not matches:
        return None
    grouped: dict[str, list[ValueFoundingMatch]] = {}
    for match in matches:
        values = grouped.setdefault(match.literal, [])
        if not any(
            item.column_ref == match.column_ref and item.value == match.value for item in values
        ):
            values.append(match)
    lines = [
        "Use these verified database value bindings when they match the question. "
        "Prefer the listed table.column and exact database value. "
        "Do not invent alternative spelling, casing, padding, or formatting.",
    ]
    for literal, items in grouped.items():
        lines.append(f"Literal mention: {literal}")
        for item in items[:12]:
            lines.append(
                f"- {item.column_ref} = {_quote_value(item.value)} "
                f"(match_score={item.score:.1f})"
            )
    return "\n".join(lines)


class ValueFoundingMatcher:
    def __init__(
        self,
        *,
        execute_sql: Callable[[str, int], Awaitable[tuple[list[str], list[dict[str, Any]], bool]]],
        score_cutoff: float = 60.0,
        max_values_per_column: int = 100000,
        max_matches_per_literal_column: int = 30,
        max_matches_total: int = 120,
    ) -> None:
        self._execute_sql = execute_sql
        self._score_cutoff = float(score_cutoff)
        self._max_values_per_column = max(1, int(max_values_per_column))
        self._max_matches_per_literal_column = max(1, int(max_matches_per_literal_column))
        self._max_matches_total = max(1, int(max_matches_total))

    async def find_matches(
        self,
        *,
        literals: list[ValueFoundingLiteral],
        schema: ChatbiDbSchemaRecord,
    ) -> list[ValueFoundingMatch]:
        valid_columns = _schema_column_refs(schema)
        cache: dict[str, list[str]] = {}
        matches: list[ValueFoundingMatch] = []
        for literal in literals:
            for column_ref in literal.columns:
                if column_ref not in valid_columns:
                    continue
                values = cache.get(column_ref)
                if values is None:
                    values = await self._fetch_distinct_values(column_ref)
                    cache[column_ref] = values
                scored = self._match_literal_to_values(literal.value, column_ref, values)
                matches.extend(scored)
        matches.sort(key=lambda item: (-item.score, item.literal, item.column_ref, item.value))
        deduped: list[ValueFoundingMatch] = []
        seen: set[tuple[str, str, str]] = set()
        for match in matches:
            key = (match.literal.casefold(), match.column_ref, match.value)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(match)
            if len(deduped) >= self._max_matches_total:
                break
        return deduped

    async def _fetch_distinct_values(self, column_ref: str) -> list[str]:
        table_name, column_name = column_ref.split(".", 1)
        sql = (
            f"SELECT DISTINCT {_quote_ident(column_name)} AS value "
            f"FROM {_quote_ident(table_name)} "
            f"WHERE {_quote_ident(column_name)} IS NOT NULL"
        )
        _, rows, _ = await self._execute_sql(sql, self._max_values_per_column)
        values: list[str] = []
        seen: set[str] = set()
        for row in rows:
            raw = row.get("value")
            if raw is None:
                continue
            text = str(raw).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            values.append(text)
        return values

    def _match_literal_to_values(
        self,
        literal: str,
        column_ref: str,
        values: list[str],
    ) -> list[ValueFoundingMatch]:
        scored: list[ValueFoundingMatch] = []
        for value in values:
            score = _similarity_score(literal, value)
            if score < self._score_cutoff:
                continue
            scored.append(
                ValueFoundingMatch(
                    literal=literal,
                    column_ref=column_ref,
                    value=value,
                    score=score,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.value))
        return scored[: self._max_matches_per_literal_column]


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _schema_column_refs(schema: ChatbiDbSchemaRecord) -> dict[str, tuple[str, str]]:
    refs: dict[str, tuple[str, str]] = {}
    for table in schema.tables:
        for column in table.columns:
            ref = f"{table.table_name}.{column.name}"
            refs[ref] = (table.table_name, column.name)
            refs[f"{table.table_name.casefold()}.{column.name.casefold()}"] = (
                table.table_name,
                column.name,
            )
    return refs


def _normalize_column_list(value: Any, *, valid_columns: dict[str, tuple[str, str]]) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        text = str(raw or "").strip()
        if not text:
            continue
        match = _COLUMN_REF_RE.match(text)
        if match is None:
            continue
        raw_ref = f"{match.group(1).strip()}.{match.group(2).strip()}"
        key = raw_ref if raw_ref in valid_columns else raw_ref.casefold()
        resolved = valid_columns.get(key)
        if resolved is None:
            continue
        ref = f"{resolved[0]}.{resolved[1]}"
        if ref not in out:
            out.append(ref)
    return out


def _similarity_score(left: str, right: str) -> float:
    if _rapidfuzz_fuzz is not None:
        return float(_rapidfuzz_fuzz.WRatio(left, right))
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio() * 100.0


def _quote_ident(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _quote_value(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


__all__ = [
    "VALUE_FOUNDING_SYSTEM",
    "ValueFoundingLiteral",
    "ValueFoundingMatch",
    "ValueFoundingMatcher",
    "build_value_founding_user_content",
    "format_value_founding_matches_for_text2sql",
    "parse_value_founding_response",
]
