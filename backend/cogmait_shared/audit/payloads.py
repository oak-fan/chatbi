"""审计与敏感操作日志的枚举与载荷模型。"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

JSONLike = Mapping[str, Any] | MutableMapping[str, Any]


def _validate_non_blank_text(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    return text


class AuditActorType(StrEnum):
    """审计记录中的操作者类型枚举。"""

    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"
    AI_AGENT = "AI_AGENT"


class ServiceID(StrEnum):
    """写入审计表时记录的服务标识。"""

    MAIN_API = "main_api"
    GATEWAY = "gateway"
    AI_SERVICE = "ai_service"
    SHARED = "shared"


class AuditResultStatus(StrEnum):
    """审计日志中的结果状态。"""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"


class AuditRiskLevel(StrEnum):
    """审计事件的风险等级。"""

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class SensitiveOperationRiskTag(StrEnum):
    """敏感操作日志的风险标签。"""

    SIGNIN_SUCCESS = "SIGNIN_SUCCESS"
    SIGNIN_FAIL = "SIGNIN_FAIL"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    OTHER = "OTHER"


class AuditBaseModel(BaseModel):
    """审计相关 Pydantic 模型的基础配置。"""

    model_config = ConfigDict(extra="forbid")


class AuditActor(AuditBaseModel):
    """触发审计事件的操作者标识。"""

    actor_id: str
    actor_type: AuditActorType = AuditActorType.HUMAN
    channel: str | None = None
    username: str | None = None
    full_name: str | None = None

    @field_validator("actor_id")
    @classmethod
    def _validate_actor_id(cls, value: str) -> str:
        return _validate_non_blank_text(value, field_name="actor_id")


class AuditResource(AuditBaseModel):
    """被操作资源的元数据。"""

    type: str
    id: str
    name: str | None = None

    @field_validator("type", "id")
    @classmethod
    def _validate_resource_text(cls, value: str) -> str:
        return _validate_non_blank_text(value, field_name="resource")


class AuditDiffItem(AuditBaseModel):
    """单个字段的差异描述。"""

    field: str
    before_value: Any = None
    after_value: Any = None

    @field_validator("field")
    @classmethod
    def _validate_field(cls, value: str) -> str:
        return _validate_non_blank_text(value, field_name="diff.field")


class AuditLogPayload(AuditBaseModel):
    """审计日志写入服务所接受的标准载荷。"""

    request_id: str
    trace_id: str | None = None
    service_id: ServiceID
    module: str
    actor: AuditActor
    ip: str | None = None
    action: str
    description: str | None = None
    resource: AuditResource
    before_snapshot: JSONLike | None = None
    after_snapshot: JSONLike | None = None
    diff: list[AuditDiffItem] | None = None
    approval_ctx: JSONLike | None = None
    result_status: AuditResultStatus = AuditResultStatus.SUCCESS
    risk_level: AuditRiskLevel = AuditRiskLevel.NORMAL
    remark: str | None = None
    extra: JSONLike | None = None

    @field_validator("request_id", "module", "action")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _validate_non_blank_text(value, field_name="audit")


class SensitiveOperationLogPayload(AuditBaseModel):
    """敏感操作（登录、权限变更等）的记录载荷。"""

    request_id: str
    service_id: ServiceID
    module: str
    description: str | None = None
    endpoint: str
    method: str
    actor: AuditActor
    ip: str | None = None
    user_agent: str | None = None
    payload_digest: str | None = None
    masked_params: JSONLike | None = None
    status_code: int | None = None
    duration_ms: int | None = None
    exception: str | None = None
    risk_tag: SensitiveOperationRiskTag | None = None
    extra: JSONLike | None = None

    @field_validator("request_id", "module", "endpoint", "method")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _validate_non_blank_text(value, field_name="sensitive_operation")


__all__ = [
    "AuditActor",
    "AuditActorType",
    "AuditDiffItem",
    "AuditLogPayload",
    "AuditResource",
    "AuditResultStatus",
    "AuditRiskLevel",
    "SensitiveOperationLogPayload",
    "SensitiveOperationRiskTag",
    "ServiceID",
]
