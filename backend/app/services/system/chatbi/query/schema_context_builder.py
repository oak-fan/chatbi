"""将 db_schema 子集格式化为 text2sql 上下文。"""

from __future__ import annotations

import json
from typing import Any

from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord


def format_schema_subset_for_llm(schema_subset: dict[str, Any]) -> str:
    """将 db_schema（全量或子集）格式化为 text2sql 上下文。"""
    return ChatbiDbSchemaRecord.from_json_dict(schema_subset).build_llm_context_summary()


def format_schema_subset_json(schema_subset: dict[str, Any]) -> str:
    return json.dumps(schema_subset, ensure_ascii=False, indent=2)


__all__ = ["format_schema_subset_for_llm", "format_schema_subset_json"]
