"""供 FastAPI `response_model` 声明使用的共享响应 Schema。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

DataT = TypeVar("DataT")


class ResponseSchema(BaseModel, Generic[DataT]):
    """与共享响应包体结构保持一致的通用响应 Schema。"""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: int = Field(..., description="响应生成时间的 13 位毫秒级 Unix 时间戳。")
    code: int = Field(..., description="业务状态码。")
    message: str = Field(..., description="响应信息。")
    data: DataT | None = Field(default=None, description="业务数据载荷。")
    request_id: str | None = Field(
        default=None,
        alias="requestId",
        description="链路追踪 ID，可选。",
    )


class EmptyPayload(BaseModel):
    """用于无业务数据返回场景的占位载荷。"""

    model_config = ConfigDict(populate_by_name=True)
