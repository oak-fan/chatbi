"""跨服务共享的数据库工具。"""

from __future__ import annotations

from .database import Database, get_default_database
from .exceptions import DatabaseError, IntegrityError, integrity_error_has_token
from .orm import AuditSoftDeleteMixin, Base, OperatorAuditMixin, SoftDeleteMixin, TimestampMixin
from .repository_utils import (
    BaseRepositoryMapper,
    apply_field_updates,
    deduplicate_preserving_order,
    escape_like,
    mark_entity_soft_deleted,
    restore_input_order,
)
from .unit_of_work import UnitOfWork

__all__ = [
    "AuditSoftDeleteMixin",
    "Base",
    "BaseRepositoryMapper",
    "Database",
    "DatabaseError",
    "IntegrityError",
    "OperatorAuditMixin",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UnitOfWork",
    "apply_field_updates",
    "deduplicate_preserving_order",
    "escape_like",
    "get_default_database",
    "integrity_error_has_token",
    "mark_entity_soft_deleted",
    "restore_input_order",
]
