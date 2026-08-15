"""Schema views for Agentar-style SQL scaling."""

from __future__ import annotations

from ......domain.system.chatbi.db_schema import (
    ChatbiDbSchemaColumnRecord,
    ChatbiDbSchemaRecord,
    ChatbiDbSchemaTableRecord,
)
from .types import AgentarSchemaView


def build_agentar_schema_views(schema: ChatbiDbSchemaRecord) -> list[AgentarSchemaView]:
    """Build prompt-visible schema variants from the selected ChatBI schema."""

    return [
        AgentarSchemaView(name="summary", text=schema.build_llm_context_summary()),
        AgentarSchemaView(name="ddl", text=_build_ddl_schema(schema)),
        AgentarSchemaView(name="light", text=_build_light_schema(schema)),
    ]


def _build_light_schema(schema: ChatbiDbSchemaRecord) -> str:
    sections: list[str] = [f"## Database: {schema.database}"]
    if schema.description:
        sections.extend(["### Database description", schema.description])
    for table in schema.tables:
        sections.append(f"## Table: {table.table_name}")
        sections.append("### Column information")
        sections.append("| column_name | column_type | column_description | value_examples |")
        sections.append("| --- | --- | --- | --- |")
        for column in table.columns:
            sections.append(
                "| {name} | {type} | {desc} | {samples} |".format(
                    name=_escape_markdown_cell(column.name),
                    type=_escape_markdown_cell(column.type),
                    desc=_escape_markdown_cell(_column_description(column)),
                    samples=_escape_markdown_cell(", ".join(column.samples[:3])),
                )
            )
        if table.foreign_keys:
            sections.append("### Foreign keys")
            for fk in table.foreign_keys:
                sections.append(
                    f"- {table.table_name}.{fk.column} = "
                    f"{fk.references.table}.{fk.references.column}"
                )
    return "\n".join(sections)


def _build_fk_summary(schema: ChatbiDbSchemaRecord) -> str:
    lines: list[str] = []
    has_fk = False
    for table in schema.tables:
        for fk in table.foreign_keys:
            has_fk = True
            lines.append(
                f"{table.table_name}.{fk.column} = {fk.references.table}.{fk.references.column}"
            )
    if not has_fk:
        return ""
    return "-- Foreign Keys:\n-- " + "\n-- ".join(lines)


def _build_ddl_schema(schema: ChatbiDbSchemaRecord) -> str:
    sections: list[str] = []
    if schema.description:
        sections.append(f"-- database: {schema.database}; description: {schema.description}")
    fk_summary = _build_fk_summary(schema)
    if fk_summary:
        sections.append(fk_summary)
    for table in schema.tables:
        sections.append(_table_to_ddl(table))
    return "\n\n".join(sections)


def _table_to_ddl(table: ChatbiDbSchemaTableRecord) -> str:
    lines = [f"CREATE TABLE {_quote_ident(table.table_name)} ("]
    column_lines: list[str] = []
    for column in table.columns:
        line = f"  {_quote_ident(column.name)} {column.type}"
        if column.constraints:
            line = f"{line} {' '.join(column.constraints)}"
        notes = []
        desc = _column_description(column)
        if desc:
            notes.append(desc)
        if column.samples:
            notes.append(f"examples: {', '.join(column.samples[:3])}")
        if notes:
            line = f"{line} -- {'; '.join(notes)}"
        column_lines.append(line)
    fk_lines = [
        (
            f"  FOREIGN KEY ({_quote_ident(fk.column)}) "
            f"REFERENCES {_quote_ident(fk.references.table)} "
            f"({_quote_ident(fk.references.column)})"
        )
        for fk in table.foreign_keys
    ]
    all_lines = column_lines + fk_lines
    for idx, line in enumerate(all_lines):
        suffix = "," if idx < len(all_lines) - 1 else ""
        lines.append(f"{line}{suffix}")
    lines.append(");")
    return "\n".join(lines)


def _column_description(column: ChatbiDbSchemaColumnRecord) -> str:
    return column.description or column.comment or ""


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _escape_markdown_cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")
