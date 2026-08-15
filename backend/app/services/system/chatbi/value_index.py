"""Value index and column profiling for ChatBI value search."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ....core.config import get_settings
from ....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord

ExecuteReadonly = Callable[[str, int, float], Awaitable[tuple[list[str], list[dict[str, Any]], bool]]]

TEXT_DISTINCT_INDEX_LIMIT = 50_000
VALUE_INDEX_MAX_VALUE_LENGTH = 200
SCHEMA_SAMPLE_MAX_VALUE_LENGTH = 80
SCHEMA_SAMPLE_SKIP_VALUE_LENGTH = 200
SCHEMA_SAMPLE_LIMIT = 6
VALUE_SEARCH_TOP_K = 30

_WORD_RE = re.compile(r"[a-z0-9]+", flags=re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^0-9a-z]+", flags=re.IGNORECASE)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(slots=True)
class ValueIndexEntry:
    table_name: str
    column_name: str
    column_type: str
    value: str
    frequency: int = 1


@dataclass(slots=True)
class ColumnProfile:
    table_name: str
    column_name: str
    column_type: str
    kind: str
    row_count: int = 0
    nonnull_count: int = 0
    distinct_count: int | None = None
    avg_length: float | None = None
    max_length: int | None = None
    min_value: str | None = None
    max_value: str | None = None
    samples: list[str] = field(default_factory=list)
    top_values: list[tuple[str, int]] = field(default_factory=list)
    indexable: bool = False
    skip_reason: str | None = None
    index_values: list[ValueIndexEntry] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.table_name}.{self.column_name}"


@dataclass(slots=True)
class ValueSearchHit:
    literal: str
    column_ref: str
    value: str
    score: float
    match_type: str
    frequency: int | None = None

class ChatbiColumnProfiler:
    """Collect per-column profiles and value-index candidates from a datasource."""

    def __init__(self, execute_sql: ExecuteReadonly) -> None:
        self._execute_sql = execute_sql

    async def profile_schema(self, schema: ChatbiDbSchemaRecord) -> dict[str, ColumnProfile]:
        profiles: dict[str, ColumnProfile] = {}
        for table in schema.tables:
            for column in table.columns:
                profile = await self._profile_column(
                    table_name=table.table_name,
                    column_name=column.name,
                    column_type=column.type,
                )
                profiles[profile.ref] = profile
        return profiles

    async def _profile_column(
        self,
        *,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> ColumnProfile:
        kind = classify_column_type(column_type)
        profile = ColumnProfile(
            table_name=table_name,
            column_name=column_name,
            column_type=column_type,
            kind=kind,
        )
        col = _quote_ident(column_name)
        table = _quote_ident(table_name)
        try:
            _, rows, _ = await self._execute_sql(
                (
                    "SELECT "
                    "COUNT(*) AS row_count, "
                    f"COUNT({col}) AS nonnull_count, "
                    f"COUNT(DISTINCT {col}) AS distinct_count, "
                    f"AVG(LENGTH(CAST({col} AS TEXT))) AS avg_length, "
                    f"MAX(LENGTH(CAST({col} AS TEXT))) AS max_length "
                    f"FROM {table}"
                ),
                1,
                60.0,
            )
            stats = rows[0] if rows else {}
            profile.row_count = _to_int(stats.get("row_count"))
            profile.nonnull_count = _to_int(stats.get("nonnull_count"))
            profile.distinct_count = _to_int_or_none(stats.get("distinct_count"))
            profile.avg_length = _to_float_or_none(stats.get("avg_length"))
            profile.max_length = _to_int_or_none(stats.get("max_length"))
        except Exception as exc:
            profile.skip_reason = f"profile_failed: {str(exc)[:120]}"
            return profile

        if profile.nonnull_count <= 0:
            profile.skip_reason = "empty_column"
            return profile

        await self._load_range_and_samples(profile)
        if _is_value_indexable(profile):
            await self._load_index_values(profile)
        elif profile.skip_reason is None:
            profile.skip_reason = "not_indexable_type_or_cardinality"
        return profile

    async def _load_range_and_samples(self, profile: ColumnProfile) -> None:
        col = _quote_ident(profile.column_name)
        table = _quote_ident(profile.table_name)
        if profile.kind in {"numeric", "datetime"}:
            try:
                _, rows, _ = await self._execute_sql(
                    f"SELECT MIN({col}) AS min_value, MAX({col}) AS max_value FROM {table}",
                    1,
                    30.0,
                )
                row = rows[0] if rows else {}
                profile.min_value = _clean_sample(row.get("min_value"), max_length=SCHEMA_SAMPLE_MAX_VALUE_LENGTH)
                profile.max_value = _clean_sample(row.get("max_value"), max_length=SCHEMA_SAMPLE_MAX_VALUE_LENGTH)
            except Exception:
                pass
        try:
            _, rows, _ = await self._execute_sql(
                (
                    f"SELECT {col} AS value, COUNT(*) AS frequency "
                    f"FROM {table} "
                    f"WHERE {col} IS NOT NULL "
                    f"AND LENGTH(CAST({col} AS TEXT)) BETWEEN 1 AND {SCHEMA_SAMPLE_SKIP_VALUE_LENGTH} "
                    f"GROUP BY {col} "
                    "ORDER BY COUNT(*) DESC "
                    f"LIMIT {SCHEMA_SAMPLE_LIMIT}"
                ),
                SCHEMA_SAMPLE_LIMIT,
                30.0,
            )
            for row in rows:
                value = _clean_sample(row.get("value"), max_length=SCHEMA_SAMPLE_MAX_VALUE_LENGTH)
                if value and value not in profile.samples:
                    profile.samples.append(value)
                if value:
                    profile.top_values.append((value, _to_int(row.get("frequency"))))
        except Exception:
            profile.samples = []

    async def _load_index_values(self, profile: ColumnProfile) -> None:
        col = _quote_ident(profile.column_name)
        table = _quote_ident(profile.table_name)
        max_rows = min(profile.distinct_count or TEXT_DISTINCT_INDEX_LIMIT, TEXT_DISTINCT_INDEX_LIMIT)
        try:
            _, rows, truncated = await self._execute_sql(
                (
                    f"SELECT {col} AS value, COUNT(*) AS frequency "
                    f"FROM {table} "
                    f"WHERE {col} IS NOT NULL "
                    f"AND LENGTH(CAST({col} AS TEXT)) BETWEEN 1 AND {VALUE_INDEX_MAX_VALUE_LENGTH} "
                    f"GROUP BY {col} "
                    "ORDER BY COUNT(*) DESC"
                ),
                max_rows,
                120.0,
            )
        except Exception as exc:
            profile.indexable = False
            profile.skip_reason = f"value_load_failed: {str(exc)[:120]}"
            return
        if truncated:
            profile.indexable = False
            profile.skip_reason = "distinct_values_exceeded_limit"
            profile.index_values = []
            return
        entries: list[ValueIndexEntry] = []
        seen: set[str] = set()
        for row in rows:
            value = _clean_sample(row.get("value"), max_length=VALUE_INDEX_MAX_VALUE_LENGTH)
            if not value or value in seen:
                continue
            seen.add(value)
            entries.append(
                ValueIndexEntry(
                    table_name=profile.table_name,
                    column_name=profile.column_name,
                    column_type=profile.column_type,
                    value=value,
                    frequency=_to_int(row.get("frequency")),
                )
            )
        profile.index_values = entries
        profile.indexable = bool(entries)
        if not entries:
            profile.skip_reason = "no_indexable_values"


class ChatbiValueIndexStore:
    """Postgres-backed value index stored beside the BIRD RAG chunks."""

    def __init__(self, database_url: str | None = None) -> None:
        settings = get_settings()
        self._database_url = (
            database_url
            or settings.chatbi_knowledge_database_url
            or settings.chatbi_multi_agent_knowledge_database_url
        )

    @property
    def enabled(self) -> bool:
        return bool(self._database_url)

    async def rebuild_datasource(
        self,
        *,
        datasource_id: int,
        db_name: str,
        profiles: dict[str, ColumnProfile],
    ) -> None:
        if not self._database_url:
            return
        rows: list[dict[str, Any]] = []
        for profile in profiles.values():
            for entry in profile.index_values:
                normalized = normalize_value(entry.value)
                if not normalized:
                    continue
                rows.append(
                    {
                        "datasource_id": datasource_id,
                        "db_name": db_name,
                        "table_name": entry.table_name,
                        "column_name": entry.column_name,
                        "column_type": entry.column_type,
                        "value_text": entry.value,
                        "normalized_value": normalized,
                        "frequency": entry.frequency,
                        "value_length": len(entry.value),
                    }
                )
        engine = create_async_engine(self._database_url, pool_pre_ping=True)
        try:
            async with engine.begin() as conn:
                await _ensure_value_index_schema(conn)
                await conn.execute(
                    text("DELETE FROM chatbi_value_index WHERE datasource_id = :datasource_id"),
                    {"datasource_id": datasource_id},
                )
                if rows:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO chatbi_value_index (
                                datasource_id, db_name, table_name, column_name, column_type,
                                value_text, normalized_value, frequency, value_length
                            )
                            VALUES (
                                :datasource_id, :db_name, :table_name, :column_name, :column_type,
                                :value_text, :normalized_value, :frequency, :value_length
                            )
                            """
                        ),
                        rows,
                    )
        finally:
            await engine.dispose()

    async def search(
        self,
        *,
        datasource_id: int,
        literal: str,
        top_k: int = VALUE_SEARCH_TOP_K,
    ) -> list[ValueSearchHit]:
        if not self._database_url:
            return []
        normalized = normalize_value(literal)
        if not _is_searchable_literal(normalized):
            return []
        engine = create_async_engine(self._database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                exact = await conn.execute(
                    text(
                        """
                        SELECT table_name, column_name, value_text, frequency, 100.0 AS score,
                               'exact' AS match_type
                        FROM chatbi_value_index
                        WHERE datasource_id = :datasource_id
                          AND normalized_value = :normalized
                        ORDER BY frequency DESC NULLS LAST, table_name, column_name
                        LIMIT :top_k
                        """
                    ),
                    {"datasource_id": datasource_id, "normalized": normalized, "top_k": top_k},
                )
                hits = _rows_to_hits(literal, exact.mappings().all())
                if len(hits) < top_k:
                    fuzzy = await conn.execute(
                        text(
                            """
                            SELECT table_name, column_name, value_text, frequency,
                                   similarity(normalized_value, :normalized) * 100.0 AS score,
                                   'trigram' AS match_type
                            FROM chatbi_value_index
                            WHERE datasource_id = :datasource_id
                              AND normalized_value <> :normalized
                              AND normalized_value % :normalized
                            ORDER BY similarity(normalized_value, :normalized) DESC,
                                     frequency DESC NULLS LAST,
                                     table_name,
                                     column_name
                            LIMIT :limit
                            """
                        ),
                        {
                            "datasource_id": datasource_id,
                            "normalized": normalized,
                            "limit": max(top_k - len(hits), 1),
                        },
                    )
                    hits.extend(_rows_to_hits(literal, fuzzy.mappings().all()))
                if len(hits) < top_k:
                    token_query = " ".join(tokenize_literal(normalized))
                    if token_query:
                        sparse = await conn.execute(
                            text(
                                """
                                SELECT table_name, column_name, value_text, frequency,
                                       ts_rank_cd(
                                           to_tsvector('simple', normalized_value),
                                           plainto_tsquery('simple', :token_query)
                                       ) * 100.0 AS score,
                                       'sparse' AS match_type
                                FROM chatbi_value_index
                                WHERE datasource_id = :datasource_id
                                  AND to_tsvector('simple', normalized_value)
                                      @@ plainto_tsquery('simple', :token_query)
                                ORDER BY score DESC, frequency DESC NULLS LAST, table_name, column_name
                                LIMIT :limit
                                """
                            ),
                            {
                                "datasource_id": datasource_id,
                                "token_query": token_query,
                                "limit": max(top_k - len(hits), 1),
                            },
                        )
                        hits.extend(_rows_to_hits(literal, sparse.mappings().all()))
            return _dedupe_hits(hits)[:top_k]
        finally:
            await engine.dispose()


def apply_column_profiles_to_schema(
    schema: ChatbiDbSchemaRecord,
    profiles: dict[str, ColumnProfile],
) -> None:
    for table in schema.tables:
        for col in table.columns:
            profile = profiles.get(f"{table.table_name}.{col.name}")
            if profile is None:
                continue
            col.samples = list(profile.samples[:SCHEMA_SAMPLE_LIMIT])
            hint = _profile_description_hint(profile)
            if hint:
                col.description = _append_description_hint(col.description, hint)


def format_value_search_hits_for_text2sql(hits: list[ValueSearchHit]) -> str | None:
    if not hits:
        return None
    grouped: dict[str, list[ValueSearchHit]] = {}
    for hit in hits:
        grouped.setdefault(hit.literal, []).append(hit)
    lines = [
        "Use these full-database value search bindings when they match the question. "
        "Prefer the listed table.column and exact database value.",
    ]
    for literal, items in grouped.items():
        lines.append(f"Literal mention: {literal}")
        for item in items[:12]:
            freq = "" if item.frequency is None else f", frequency={item.frequency}"
            lines.append(
                f"- {item.column_ref} = {_quote_value(item.value)} "
                f"(search_score={item.score:.1f}, match_type={item.match_type}{freq})"
            )
    return "\n".join(lines)


def classify_column_type(type_name: str) -> str:
    t = type_name.lower()
    if any(token in t for token in ("char", "text", "string", "varchar", "enum", "uuid")):
        return "text"
    if any(token in t for token in ("date", "time", "timestamp")):
        return "datetime"
    if any(token in t for token in ("int", "real", "double", "float", "numeric", "decimal", "number")):
        return "numeric"
    if "bool" in t:
        return "boolean"
    return "other"


def normalize_value(value: str) -> str:
    text_value = _NON_WORD_RE.sub(" ", str(value or "").casefold())
    return _SPACE_RE.sub(" ", text_value).strip()


def tokenize_literal(value: str) -> list[str]:
    return [token for token in _WORD_RE.findall(value.casefold()) if token not in _STOP_WORDS]


def _is_value_indexable(profile: ColumnProfile) -> bool:
    if profile.kind not in {"text", "boolean"}:
        return False
    if profile.distinct_count is None or profile.distinct_count <= 0:
        return False
    if profile.distinct_count > TEXT_DISTINCT_INDEX_LIMIT:
        profile.skip_reason = "distinct_count_too_high"
        return False
    if profile.avg_length is not None and profile.avg_length > 160:
        profile.skip_reason = "average_value_too_long"
        return False
    return True


def _is_searchable_literal(normalized: str) -> bool:
    tokens = tokenize_literal(normalized)
    if not tokens:
        return False
    if len(tokens) == 1 and len(tokens[0]) <= 1:
        return False
    return True


def _profile_description_hint(profile: ColumnProfile) -> str | None:
    parts: list[str] = []
    if profile.kind in {"numeric", "datetime"}:
        range_parts = []
        if profile.min_value is not None:
            range_parts.append(f"min={profile.min_value}")
        if profile.max_value is not None:
            range_parts.append(f"max={profile.max_value}")
        if range_parts:
            parts.append("value range: " + ", ".join(range_parts))
    if profile.kind == "datetime":
        fmt = _datetime_format_hint(profile.samples)
        if fmt:
            parts.append(f"format={fmt}")
    if profile.kind in {"numeric", "datetime", "boolean"} and profile.distinct_count is not None:
        parts.append(f"distinct_count={profile.distinct_count}")
    if not parts:
        return None
    return "Profile: " + "; ".join(parts) + "."


def _append_description_hint(description: str, hint: str) -> str:
    base = (description or "").strip()
    if hint in base:
        return base
    return f"{base} {hint}".strip()


def _datetime_format_hint(samples: list[str]) -> str | None:
    for sample in samples:
        value = sample.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return "YYYY-MM-DD"
        if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", value):
            return "YYYY-MM-DD HH:MM:SS"
        if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", value):
            return "MM/DD/YYYY or DD/MM/YYYY"
        if re.match(r"^\d{2}:\d{2}(:\d{2})?$", value):
            return "HH:MM[:SS]"
    return None


async def _ensure_value_index_schema(conn: Any) -> None:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS chatbi_value_index (
                id BIGSERIAL PRIMARY KEY,
                datasource_id BIGINT NOT NULL,
                db_name TEXT NOT NULL,
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                column_type TEXT NOT NULL,
                value_text TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                frequency BIGINT,
                value_length INTEGER,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_chatbi_value_index_exact
            ON chatbi_value_index (datasource_id, normalized_value)
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_chatbi_value_index_trgm
            ON chatbi_value_index USING GIN (normalized_value gin_trgm_ops)
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_chatbi_value_index_fts
            ON chatbi_value_index USING GIN (to_tsvector('simple', normalized_value))
            """
        )
    )


def _rows_to_hits(literal: str, rows: list[Any]) -> list[ValueSearchHit]:
    out: list[ValueSearchHit] = []
    for row in rows:
        table = str(row.get("table_name") or "")
        column = str(row.get("column_name") or "")
        value = str(row.get("value_text") or "")
        if not table or not column or not value:
            continue
        out.append(
            ValueSearchHit(
                literal=literal,
                column_ref=f"{table}.{column}",
                value=value,
                score=_to_float_or_none(row.get("score")) or 0.0,
                match_type=str(row.get("match_type") or "unknown"),
                frequency=_to_int_or_none(row.get("frequency")),
            )
        )
    return out


def _dedupe_hits(hits: list[ValueSearchHit]) -> list[ValueSearchHit]:
    hits.sort(key=lambda item: (-item.score, -(item.frequency or 0), item.column_ref, item.value))
    out: list[ValueSearchHit] = []
    seen: set[tuple[str, str, str]] = set()
    for hit in hits:
        key = (hit.literal.casefold(), hit.column_ref, hit.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def _quote_ident(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _quote_value(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _clean_sample(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    return text_value[:max_length]


def _to_int(value: Any) -> int:
    parsed = _to_int_or_none(value)
    return parsed or 0


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ChatbiColumnProfiler",
    "ChatbiValueIndexStore",
    "ColumnProfile",
    "ValueSearchHit",
    "apply_column_profiles_to_schema",
    "classify_column_type",
    "format_value_search_hits_for_text2sql",
    "normalize_value",
    "tokenize_literal",
]
