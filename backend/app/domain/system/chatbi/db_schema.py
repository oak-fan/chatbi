"""ChatBI 库表结构领域对象（连接器产出与落库 db_schema JSON 同形）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _strip_required(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} 不能为空"
        raise ValueError(msg)
    return text


def _normalize_optional_str(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


@dataclass(slots=True)
class ChatbiDbSchemaForeignKeyRefRecord:
    """外键引用目标表与列。"""

    table: str
    column: str

    def __post_init__(self) -> None:
        self.table = _strip_required(self.table, field_name="references.table")
        self.column = _strip_required(self.column, field_name="references.column")

    def to_json_dict(self) -> dict[str, str]:
        return {"table": self.table, "column": self.column}

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> ChatbiDbSchemaForeignKeyRefRecord:
        if not isinstance(payload, dict):
            msg = "references 必须为对象"
            raise ValueError(msg)
        return cls(
            table=str(payload.get("table", "")),
            column=str(payload.get("column", "")),
        )


@dataclass(slots=True)
class ChatbiDbSchemaForeignKeyRecord:
    """单条外键约束（本表列 → 引用）。"""

    column: str
    references: ChatbiDbSchemaForeignKeyRefRecord
    constraint_name: str

    def __post_init__(self) -> None:
        self.column = _strip_required(self.column, field_name="foreign_key.column")
        self.constraint_name = _normalize_optional_str(self.constraint_name)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "references": self.references.to_json_dict(),
            "constraint_name": self.constraint_name,
        }

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> ChatbiDbSchemaForeignKeyRecord:
        if not isinstance(payload, dict):
            msg = "foreign_key 项必须为对象"
            raise ValueError(msg)
        return cls(
            column=str(payload.get("column", "")),
            references=ChatbiDbSchemaForeignKeyRefRecord.from_json_dict(
                payload.get("references") or {}
            ),
            constraint_name=str(payload.get("constraint_name") or ""),
        )


@dataclass(slots=True)
class ChatbiDbSchemaColumnRecord:
    """单列元数据（含数据库注释与 LLM 业务描述）。"""

    name: str
    type: str
    constraints: list[str] = field(default_factory=list)
    comment: str = ""
    description: str = ""
    samples: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = _strip_required(self.name, field_name="column.name")
        self.type = _strip_required(self.type, field_name="column.type")
        self.comment = _normalize_optional_str(self.comment)
        self.description = _normalize_optional_str(self.description)
        normalized: list[str] = []
        for item in self.constraints:
            text = str(item).strip()
            if text:
                normalized.append(text)
        self.constraints = normalized
        self.samples = [str(s)[:200] for s in self.samples if s is not None and str(s).strip()]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "constraints": list(self.constraints),
            "comment": self.comment,
            "description": self.description,
            "samples": list(self.samples),
        }

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> ChatbiDbSchemaColumnRecord:
        if not isinstance(payload, dict):
            msg = "column 项必须为对象"
            raise ValueError(msg)
        raw_constraints = payload.get("constraints") or []
        if not isinstance(raw_constraints, list):
            msg = "constraints 必须为数组"
            raise ValueError(msg)
        raw_samples = payload.get("samples") or []
        if not isinstance(raw_samples, list):
            msg = "samples 必须为数组"
            raise ValueError(msg)
        return cls(
            name=str(payload.get("name", "")),
            type=str(payload.get("type", "")),
            constraints=[str(c) for c in raw_constraints],
            comment=str(payload.get("comment") or ""),
            description=str(payload.get("description") or ""),
            samples=[str(s) for s in raw_samples],
        )


@dataclass(slots=True)
class ChatbiDbSchemaTableRecord:
    """单张表及其列、外键列表。"""

    table_name: str
    columns: list[ChatbiDbSchemaColumnRecord] = field(default_factory=list)
    foreign_keys: list[ChatbiDbSchemaForeignKeyRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.table_name = _strip_required(self.table_name, field_name="table_name")
        if not self.columns:
            msg = "columns 必须为非空数组"
            raise ValueError(msg)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "columns": [col.to_json_dict() for col in self.columns],
            "foreign_keys": [fk.to_json_dict() for fk in self.foreign_keys],
        }

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> ChatbiDbSchemaTableRecord:
        if not isinstance(payload, dict):
            msg = "table 项必须为对象"
            raise ValueError(msg)
        raw_columns = payload.get("columns") or []
        if not isinstance(raw_columns, list) or not raw_columns:
            msg = "columns 必须为非空数组"
            raise ValueError(msg)
        raw_fks = payload.get("foreign_keys") or []
        if not isinstance(raw_fks, list):
            msg = "foreign_keys 必须为数组"
            raise ValueError(msg)
        return cls(
            table_name=str(payload.get("table_name", "")),
            columns=[ChatbiDbSchemaColumnRecord.from_json_dict(c) for c in raw_columns],
            foreign_keys=[ChatbiDbSchemaForeignKeyRecord.from_json_dict(f) for f in raw_fks],
        )


@dataclass(slots=True)
class ChatbiDbSchemaRecord:
    """连接器 get_structure 与落库 db_schema 的统一结构。"""

    database: str
    description: str = ""
    tables: list[ChatbiDbSchemaTableRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.database = _strip_required(self.database, field_name="database")
        self.description = _normalize_optional_str(self.description)
        if not self.tables:
            msg = "tables 必须为非空数组"
            raise ValueError(msg)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "description": self.description,
            "tables": [table.to_json_dict() for table in self.tables],
        }

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> ChatbiDbSchemaRecord:
        if not isinstance(payload, dict):
            msg = "db_schema 必须为对象"
            raise ValueError(msg)
        raw_tables = payload.get("tables") or []
        if not isinstance(raw_tables, list) or not raw_tables:
            msg = "tables 必须为非空数组"
            raise ValueError(msg)
        return cls(
            database=str(payload.get("database", "")),
            description=str(payload.get("description") or ""),
            tables=[ChatbiDbSchemaTableRecord.from_json_dict(t) for t in raw_tables],
        )

    def apply_descriptions(
        self,
        *,
        datasource_description: str,
        column_descriptions: dict[str, str],
    ) -> None:
        """将 LLM 返回的描述写入结构；column_descriptions 键为「表名.列名」。"""
        self.description = _normalize_optional_str(datasource_description)
        for table in self.tables:
            for col in table.columns:
                key = f"{table.table_name}.{col.name}"
                if key in column_descriptions:
                    col.description = column_descriptions[key].strip()

    def build_llm_context_summary(self) -> str:
        """将 db_schema（全量或子集）格式化为 LLM 可读文本。"""
        lines: list[str] = [f"database={self.database}"]
        if self.description:
            lines.append(f"description={self.description}")
        for table in self.tables:
            lines.append(f"table {table.table_name}:")
            for col in table.columns:
                attrs: list[str] = []
                if col.description:
                    attrs.append(f"description={col.description}")
                if col.comment:
                    attrs.append(f"comment={col.comment}")
                if col.constraints:
                    attrs.append(f"constraints={','.join(col.constraints)}")
                if col.samples:
                    attrs.append(f"samples={','.join(col.samples)}")
                col_line = f"  - {col.name} ({col.type})"
                if attrs:
                    col_line = f"{col_line}: {' | '.join(attrs)}"
                lines.append(col_line)
            if table.foreign_keys:
                lines.append("  foreign_keys:")
                for fk in table.foreign_keys:
                    lines.append(f"  - {fk.column} -> {fk.references.table}.{fk.references.column}")
        return "\n".join(lines)


__all__ = [
    "ChatbiDbSchemaColumnRecord",
    "ChatbiDbSchemaForeignKeyRecord",
    "ChatbiDbSchemaForeignKeyRefRecord",
    "ChatbiDbSchemaRecord",
    "ChatbiDbSchemaTableRecord",
]
