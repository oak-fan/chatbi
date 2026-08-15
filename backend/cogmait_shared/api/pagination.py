"""分页响应组装工具。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_page_payload(
    *,
    records: Sequence[Any],
    total: int,
    current: int,
    page_size: int,
    item_schema: type[Any],
    response_schema: type[Any],
    list_field: str = "items",
    extra_fields: dict[str, Any] | None = None,
) -> Any:
    """构造统一分页响应载荷。

    response_schema 需要支持列表字段、total、current、page_size 四个输入字段。
    """
    payload = {
        list_field: [item_schema.model_validate(item) for item in records],
        "total": total,
        "current": current,
        "page_size": page_size,
    }
    if extra_fields:
        payload.update(extra_fields)
    return response_schema.model_validate(
        payload,
    )
