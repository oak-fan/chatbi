"""ChatBI 问数流事件序列化（service 层共享，供 API SSE 与 benchmark 复用）。"""

from __future__ import annotations

from typing import Any

from .....constants.chatbi.query import (
    CHATBI_SSE_BUSINESS_KNOWLEDGE_RECALL,
    CHATBI_SSE_CLARIFICATION_REQUIRED,
    CHATBI_SSE_COMPLETED,
    CHATBI_SSE_DATA,
    CHATBI_SSE_INTENT,
    CHATBI_SSE_QSQL_RECALL,
    CHATBI_SSE_RAG_KNOWLEDGE_RECALL,
    CHATBI_SSE_SCHEMA_LINKING,
    CHATBI_SSE_SCHEMA_SELECTED,
    CHATBI_SSE_SQL_CANDIDATES,
    CHATBI_SSE_SQL_GROUP_AUDIT,
    CHATBI_SSE_SQL_VALIDATE,
    CHATBI_SSE_VALUE_FOUNDING,
    CHATBI_SSE_VALUE_SEARCH,
)
from .....domain.system.chatbi.query import ChatbiQueryStreamEvent


def serialize_chatbi_stream_event(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    """将内部 snake_case 流事件转换为对外 camelCase SSE 载荷。"""
    data = _base_stream_event_data(event)
    data.update(_event_specific_stream_data(event))
    _append_optional_stream_data(data, event)
    if event.error:
        data["error"] = _error_to_stream_data(event.error)
    return _camelize_stream_payload(data)


def _base_stream_event_data(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    data: dict[str, Any] = {"event": event.event}
    if event.request_id is not None:
        data["request_id"] = event.request_id
    if event.session_id is not None:
        data["session_id"] = str(event.session_id)
    if event.question is not None:
        data["question"] = event.question
    if event.is_degraded is not None:
        data["is_degraded"] = event.is_degraded
    if event.intent is not None:
        data["intent"] = event.intent
    return data


def _event_specific_stream_data(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    event_type = event.event
    if event_type == CHATBI_SSE_INTENT:
        return _intent_stream_data(event)
    if event_type == CHATBI_SSE_CLARIFICATION_REQUIRED:
        return _clarification_stream_data(event)
    if event_type == CHATBI_SSE_DATA:
        return _query_data_stream_data(event)
    if event_type == CHATBI_SSE_BUSINESS_KNOWLEDGE_RECALL:
        return {"items": _business_knowledge_stream_items(event.business_knowledge_hits)}
    if event_type == CHATBI_SSE_SCHEMA_LINKING:
        return dict(event.schema_linking)
    if event_type == CHATBI_SSE_SCHEMA_SELECTED:
        return {"fields": event.schema_fields}
    if event_type == CHATBI_SSE_QSQL_RECALL:
        return {"items": _qsql_stream_items(event.qsql_hits)}
    if event_type == CHATBI_SSE_SQL_CANDIDATES:
        return {
            "items": _sql_candidate_stream_items(event.sql_candidates),
            "selection": dict(event.sql_selection),
        }
    if event_type == CHATBI_SSE_SQL_VALIDATE:
        return {"validation": dict(event.validation)}
    if event_type == CHATBI_SSE_SQL_GROUP_AUDIT:
        return {"group_audit": dict(event.group_audit)}
    if event_type == CHATBI_SSE_COMPLETED:
        return _completed_stream_data(event)
    if event_type == CHATBI_SSE_VALUE_FOUNDING:
        return _value_founding_stream_data(event)
    if event_type == CHATBI_SSE_VALUE_SEARCH:
        return {"matches": event.value_search_matches}
    if event_type == CHATBI_SSE_RAG_KNOWLEDGE_RECALL:
        return {"items": event.rag_knowledge_hits}
    return {}


def _append_optional_stream_data(
    data: dict[str, Any],
    event: ChatbiQueryStreamEvent,
) -> None:
    if event.sql is not None:
        data["sql"] = event.sql
    if event.sql_fixed is not None:
        data["fixed"] = event.sql_fixed
    if event.text is not None:
        data["text"] = event.text


def _intent_stream_data(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    data: dict[str, Any] = {"missing_datasource": bool(event.missing_datasource)}
    detail = event.intent_detail
    if detail.get("datasource_id") is not None:
        data["datasource_id"] = str(detail["datasource_id"])
    if detail.get("choice") is not None:
        data["choice"] = detail["choice"]
    if detail.get("brief_explanation") is not None:
        data["brief_explanation"] = detail["brief_explanation"]
    if detail.get("message") is not None:
        data["message"] = detail["message"]
    return data


def _clarification_stream_data(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    return {
        "token": event.clarification_token or "",
        "question": event.question or "",
        "options": event.options,
    }


def _query_data_stream_data(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    return {
        "columns": event.columns,
        "rows": event.rows,
        "truncated": bool(event.truncated),
    }


def _completed_stream_data(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if event.total_tokens is not None:
        data["total_tokens"] = event.total_tokens
    return data


def _value_founding_stream_data(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    return {
        "literals": event.value_founding_literals,
        "matches": event.value_founding_matches,
    }


def _business_knowledge_stream_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "business_knowledge_id": str(item.get("business_knowledge_id", "")),
            "score": item.get("score"),
            "content": item.get("content"),
            "display_content": item.get("display_content") or item.get("content"),
            "kind": item.get("kind"),
            "scope": item.get("scope"),
            "datasource_id": (
                str(item["datasource_id"]) if item.get("datasource_id") is not None else None
            ),
            "datasource_name": item.get("datasource_name"),
        }
        for item in items
    ]


def _qsql_stream_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "qsql_id": str(item.get("qsql_id", "")),
            "score": item.get("score"),
            "vector_score": item.get("vector_score"),
            "lexical_score": item.get("lexical_score"),
            "skeleton_score": item.get("skeleton_score"),
            "question": item.get("question"),
            "sql_body": item.get("sql_body"),
            "scope": item.get("scope"),
            "source_dataset": item.get("source_dataset"),
            "source_db_id": item.get("source_db_id"),
            "retrieval_strategy": item.get("retrieval_strategy"),
        }
        for item in items
    ]


def _sql_candidate_stream_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path_name": item.get("path_name"),
            "schema_format": item.get("schema_format"),
            "prompt_style": item.get("prompt_style"),
            "sql": item.get("sql"),
            "original_sql": item.get("original_sql"),
            "fixed": bool(item.get("fixed")),
            "generation_error": item.get("generation_error"),
            "execute_error": item.get("execute_error"),
            "fix_error": item.get("fix_error"),
            "columns": item.get("columns") if isinstance(item.get("columns"), list) else [],
            "rows": item.get("rows") if isinstance(item.get("rows"), list) else [],
            "row_count": item.get("row_count"),
            "truncated": bool(item.get("truncated")),
            "result_signature": item.get("result_signature"),
            "group_id": item.get("group_id"),
            "group_size": item.get("group_size"),
            "score": item.get("score"),
            "wins": item.get("wins"),
            "comparisons": item.get("comparisons"),
            "selected": bool(item.get("selected")),
            "selection_reason": item.get("selection_reason"),
        }
        for item in items
    ]


def _error_to_stream_data(error: dict[str, Any]) -> dict[str, Any]:
    return dict(error)


def _camelize_stream_payload(data: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, value in data.items():
        converted[_to_camel_case(key)] = value if key == "rows" else _camelize_stream_value(value)
    return converted


def _camelize_stream_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _camelize_stream_payload(value)
    if isinstance(value, list):
        return [_camelize_stream_value(item) for item in value]
    return value


def _to_camel_case(key: str) -> str:
    head, *tail = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


__all__ = ["serialize_chatbi_stream_event"]
