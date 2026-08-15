"""ChatBI db_schema JSON 校验与子集抽取。"""

from __future__ import annotations

from typing import Any

from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord


def validate_db_schema(payload: dict[str, Any]) -> ChatbiDbSchemaRecord:
    """校验并规范化为领域结构。"""
    return ChatbiDbSchemaRecord.from_json_dict(payload)


def subset_db_schema(
    db_schema: dict[str, Any],
    selected: set[tuple[str, str]],
) -> dict[str, Any]:
    """按 (table_name, column_name) 从完整 schema 抽取子集。"""
    record = validate_db_schema(db_schema)
    if not selected:
        return {
            "database": record.database,
            "description": record.description,
            "tables": [],
        }
    selected_tables = {table_name for table_name, _column_name in selected}
    include_columns: dict[str, set[str]] = {
        table_name: {column_name for tname, column_name in selected if tname == table_name}
        for table_name in selected_tables
    }
    fk_keys: set[tuple[str, str, str, str]] = set()
    for table in record.tables:
        if table.table_name not in selected_tables:
            continue
        for fk in table.foreign_keys:
            ref_table = fk.references.table
            if ref_table not in selected_tables:
                continue
            include_columns.setdefault(table.table_name, set()).add(fk.column)
            include_columns.setdefault(ref_table, set()).add(fk.references.column)
            fk_keys.add((table.table_name, fk.column, ref_table, fk.references.column))

    tables_out: list[dict[str, Any]] = []
    for table in record.tables:
        table_columns = include_columns.get(table.table_name, set())
        cols = [col.to_json_dict() for col in table.columns if col.name in table_columns]
        if not cols:
            continue
        fks = [
            fk.to_json_dict()
            for fk in table.foreign_keys
            if (
                table.table_name,
                fk.column,
                fk.references.table,
                fk.references.column,
            )
            in fk_keys
        ]
        tables_out.append({"table_name": table.table_name, "columns": cols, "foreign_keys": fks})
    return {
        "database": record.database,
        "description": record.description,
        "tables": tables_out,
    }


__all__ = ["subset_db_schema", "validate_db_schema"]
