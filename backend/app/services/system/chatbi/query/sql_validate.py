"""ChatBI generated SQL validation context."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp

from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from .prompts import json_safe_rows

_CONNECTOR_DIALECT = {
    "SQLITE": "sqlite",
    "MYSQL": "mysql",
    "POSTGRESQL": "postgres",
}


@dataclass(frozen=True, slots=True)
class SqlValidateColumn:
    table_name: str | None
    column_name: str
    column_type: str | None
    reference: str
    exists: bool
    samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "column_name": self.column_name,
            "column_type": self.column_type,
            "reference": self.reference,
            "exists": self.exists,
            "samples": list(self.samples),
        }


@dataclass(frozen=True, slots=True)
class SqlValidateExecution:
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "columns": list(self.columns),
            "rows": json_safe_rows(self.rows),
            "truncated": self.truncated,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class SqlValidateContext:
    parse_status: str
    referenced_columns: list[SqlValidateColumn]
    missing_columns: list[SqlValidateColumn]
    execution: SqlValidateExecution

    def as_dict(self) -> dict[str, Any]:
        return {
            "parse_status": self.parse_status,
            "referenced_columns": [item.as_dict() for item in self.referenced_columns],
            "missing_columns": [item.as_dict() for item in self.missing_columns],
            "execution": self.execution.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SqlValidateResult:
    original_sql: str
    validated_sql: str
    changed: bool
    latency_ms: int
    context: dict[str, Any]

    def to_validation_payload(self) -> dict[str, Any]:
        return {
            "original_sql": self.original_sql,
            "validated_sql": self.validated_sql,
            "changed": self.changed,
            "latency_ms": self.latency_ms,
            "context": self.context,
        }


def connector_type_to_sqlglot_dialect(connector_type: str | None) -> str:
    if not connector_type:
        return "sqlite"
    return _CONNECTOR_DIALECT.get(connector_type.strip().upper(), "sqlite")


def build_sql_validate_context(
    *,
    sql: str,
    schema: ChatbiDbSchemaRecord,
    connector_type: str | None,
    execution: SqlValidateExecution,
) -> SqlValidateContext:
    referenced_columns, parse_status = extract_referenced_columns(
        sql=sql,
        schema=schema,
        connector_type=connector_type,
    )
    missing = [item for item in referenced_columns if not item.exists]
    return SqlValidateContext(
        parse_status=parse_status,
        referenced_columns=referenced_columns,
        missing_columns=missing,
        execution=execution,
    )


def extract_referenced_columns(
    *,
    sql: str,
    schema: ChatbiDbSchemaRecord,
    connector_type: str | None,
) -> tuple[list[SqlValidateColumn], str]:
    text = (sql or "").strip()
    if not text:
        return [], "EMPTY"
    try:
        expression = sqlglot.parse_one(
            text,
            read=connector_type_to_sqlglot_dialect(connector_type),
        )
    except Exception:
        return [], "PARSE_FAILED"

    schema_index = _SchemaIndex.from_schema(schema)
    cte_names = _collect_cte_names(expression)
    alias_map = _collect_alias_map(expression, cte_names)
    physical_tables = set(alias_map.values())
    out: list[SqlValidateColumn] = []
    seen: set[str] = set()
    for column in expression.find_all(exp.Column):
        table_name = _resolve_column_table(
            column=column,
            alias_map=alias_map,
            cte_names=cte_names,
            physical_tables=physical_tables,
            schema_index=schema_index,
        )
        column_name = _normalize_ident(column.name)
        if not column_name:
            continue
        reference = f"{table_name}.{column_name}" if table_name else column_name
        if reference in seen:
            continue
        seen.add(reference)
        exists = schema_index.has_column(table_name, column_name)
        samples = schema_index.samples_for(table_name, column_name) if exists else []
        column_type = schema_index.type_for(table_name, column_name) if exists else None
        out.append(
            SqlValidateColumn(
                table_name=table_name,
                column_name=column_name,
                column_type=column_type,
                reference=reference,
                exists=exists,
                samples=samples,
            )
        )
    return out, "SUCCESS"


@dataclass(frozen=True, slots=True)
class _SchemaIndex:
    tables: dict[str, dict[str, dict[str, Any]]]
    columns_to_tables: dict[str, set[str]]

    @classmethod
    def from_schema(cls, schema: ChatbiDbSchemaRecord) -> _SchemaIndex:
        tables: dict[str, dict[str, dict[str, Any]]] = {}
        columns_to_tables: dict[str, set[str]] = {}
        for table in schema.tables:
            table_name = _normalize_ident(table.table_name)
            table_cols: dict[str, dict[str, Any]] = {}
            for column in table.columns:
                column_name = _normalize_ident(column.name)
                samples = [str(item) for item in column.samples[:3]]
                table_cols[column_name] = {"type": column.type, "samples": samples}
                columns_to_tables.setdefault(column_name, set()).add(table_name)
            tables[table_name] = table_cols
        return cls(tables=tables, columns_to_tables=columns_to_tables)

    def has_column(self, table_name: str | None, column_name: str) -> bool:
        normalized_column = _normalize_ident(column_name)
        if table_name:
            return normalized_column in self.tables.get(_normalize_ident(table_name), {})
        return normalized_column in self.columns_to_tables

    def samples_for(self, table_name: str | None, column_name: str) -> list[str]:
        normalized_column = _normalize_ident(column_name)
        if table_name:
            table_columns = self.tables.get(_normalize_ident(table_name), {})
            meta = table_columns.get(normalized_column, {})
            samples = meta.get("samples", []) if isinstance(meta, dict) else []
            return [str(item) for item in samples]
        tables = self.columns_to_tables.get(normalized_column) or set()
        for item in sorted(tables):
            meta = self.tables.get(item, {}).get(normalized_column, {})
            samples = meta.get("samples", []) if isinstance(meta, dict) else []
            if samples:
                return [str(value) for value in samples]
        return []


    def type_for(self, table_name: str | None, column_name: str) -> str | None:
        normalized_column = _normalize_ident(column_name)
        if table_name:
            table_columns = self.tables.get(_normalize_ident(table_name), {})
            meta = table_columns.get(normalized_column, {})
            value = meta.get("type") if isinstance(meta, dict) else None
            return str(value) if value else None
        tables = self.columns_to_tables.get(normalized_column) or set()
        for item in sorted(tables):
            meta = self.tables.get(item, {}).get(normalized_column, {})
            value = meta.get("type") if isinstance(meta, dict) else None
            if value:
                return str(value)
        return None
    def unique_table_for_column(
        self,
        column_name: str,
        *,
        candidate_tables: Iterable[str],
    ) -> str | None:
        normalized_column = _normalize_ident(column_name)
        owning_tables = self.columns_to_tables.get(normalized_column) or set()
        matches = {_normalize_ident(item) for item in candidate_tables} & owning_tables
        if len(matches) == 1:
            return next(iter(matches))
        if not matches and len(owning_tables) == 1:
            return next(iter(owning_tables))
        return None


def _normalize_ident(value: str) -> str:
    return value.strip().strip('`"[]').lower()


def _collect_cte_names(expression: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in expression.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(_normalize_ident(alias))
    return names


def _collect_alias_map(expression: exp.Expression, cte_names: set[str]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for table in expression.find_all(exp.Table):
        physical = _normalize_ident(table.name)
        if not physical or physical in cte_names:
            continue
        alias = _normalize_ident(table.alias_or_name)
        alias_map[alias] = physical
        alias_map[physical] = physical
    return alias_map


def _resolve_column_table(
    *,
    column: exp.Column,
    alias_map: dict[str, str],
    cte_names: set[str],
    physical_tables: set[str],
    schema_index: _SchemaIndex,
) -> str | None:
    raw_table = _normalize_ident(column.table)
    if raw_table and raw_table not in cte_names:
        return alias_map.get(raw_table, raw_table)
    if len(physical_tables) == 1:
        return next(iter(physical_tables))
    return schema_index.unique_table_for_column(
        _normalize_ident(column.name),
        candidate_tables=physical_tables,
    )


__all__ = [
    "SqlValidateContext",
    "SqlValidateExecution",
    "SqlValidateResult",
    "build_sql_validate_context",
]
