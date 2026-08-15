"""审计相关 ORM 模型定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .payloads import AuditResultStatus, AuditRiskLevel

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class AuditBase(DeclarativeBase):
    """审计相关 ORM 模型的 Declarative 基类。"""


class SysAuditLog(AuditBase):
    """`sys_audit_log` 表的 ORM 模型。"""

    __tablename__ = "sys_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="全局雪花 ID")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="链路 ID，来自中间件")
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="OpenTelemetry/链路跟踪 ID")
    service_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="来源服务标识")
    module: Mapped[str | None] = mapped_column(String(128), comment="模块名称")
    actor_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="操作者 ID（用户/系统账号/Agent）",
    )
    actor_username: Mapped[str | None] = mapped_column(String(64), comment="操作者用户名快照")
    actor_full_name: Mapped[str | None] = mapped_column(String(64), comment="操作者姓名快照")
    actor_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="操作者类型（HUMAN/SYSTEM/AI_AGENT）",
    )
    ip: Mapped[str | None] = mapped_column(String(64), comment="客户端 IP")
    action: Mapped[str] = mapped_column(String(64), nullable=False, comment="业务动作编码")
    description: Mapped[str | None] = mapped_column(String(255), comment="操作描述")
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="被操作资源类型")
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="资源唯一标识")
    resource_name: Mapped[str | None] = mapped_column(String(128), comment="资源展示名")
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        default=None,
        comment="精简前镜像",
    )
    after_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        default=None,
        nullable=True,
        comment="精简后镜像",
    )
    diff: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON_TYPE,
        default=None,
        comment="结构化差异",
    )
    approval_ctx: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        default=None,
        comment="审批链、风控规则等上下文",
    )
    result_status: Mapped[str] = mapped_column(
        String(32),
        default=AuditResultStatus.SUCCESS.value,
        nullable=False,
        comment="审计结果状态",
    )
    risk_level: Mapped[str] = mapped_column(
        String(16),
        default=AuditRiskLevel.NORMAL.value,
        nullable=False,
        comment="风险等级",
    )
    remark: Mapped[str | None] = mapped_column(String(255), comment="业务备注/原因")
    extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        default=None,
        comment="扩展键值",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="写入时间",
    )
    created_by: Mapped[str] = mapped_column(
        String(64),
        default="audit_service",
        nullable=False,
        comment="系统账号，默认 audit_service",
    )

    __table_args__ = (
        Index("idx_audit_module_at", "module", "created_at"),
        Index("idx_audit_resource_at", "resource_type", "resource_id", "created_at"),
        Index("idx_audit_actor_at", "actor_id", "created_at"),
        Index("idx_audit_actor_username", "actor_username"),
        Index("idx_audit_actor_full_name", "actor_full_name"),
        Index("idx_audit_action", "action", "risk_level"),
        {"comment": "审计日志表"},
    )


class SysSensitiveOpLog(AuditBase):
    """`sys_sensitive_op_log` 表的 ORM 模型。"""

    __tablename__ = "sys_sensitive_op_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="全局雪花 ID")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="链路 ID")
    service_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="来源服务标识")
    module: Mapped[str] = mapped_column(String(64), nullable=False, comment="模块编码")
    description: Mapped[str | None] = mapped_column(String(255), comment="操作描述")
    endpoint: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="接口路径或内部事件名",
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False, comment="HTTP 方法或操作类型")
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="操作主体 ID")
    actor_username: Mapped[str | None] = mapped_column(String(64), comment="操作者用户名快照")
    actor_full_name: Mapped[str | None] = mapped_column(String(64), comment="操作者姓名快照")
    actor_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="操作者类型（HUMAN/SYSTEM/AI_AGENT）",
    )
    ip: Mapped[str | None] = mapped_column(String(64), comment="客户端 IP")
    user_agent: Mapped[str | None] = mapped_column(String(255), comment="用户代理")
    payload_digest: Mapped[str | None] = mapped_column(String(128), comment="请求体摘要")
    masked_params: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        default=None,
        comment="掩码后的请求参数",
    )
    status_code: Mapped[int | None] = mapped_column(Integer, comment="响应状态码")
    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="耗时（毫秒）")
    exception: Mapped[str | None] = mapped_column(Text, comment="异常摘要")
    risk_tag: Mapped[str | None] = mapped_column(String(32), comment="风险标签")
    extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        default=None,
        comment="扩展上下文",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="写入时间",
    )

    __table_args__ = (
        Index("idx_sensitive_actor_at", "actor_id", "created_at"),
        Index("idx_sensitive_actor_username", "actor_username"),
        Index("idx_sensitive_actor_full_name", "actor_full_name"),
        Index("idx_sensitive_endpoint", "module", "endpoint", "created_at"),
        Index("idx_sensitive_risk", "risk_tag", "created_at"),
        {"comment": "敏感操作日志表"},
    )


__all__ = [
    "AuditBase",
    "SysAuditLog",
    "SysSensitiveOpLog",
]
