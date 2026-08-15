"""ChatBI 后台任务领域枚举。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ....constants.chatbi.task import (
    CHATBI_ACTIVE_TASK_STATUSES,
    CHATBI_TASK_STATUS_FAILED,
    CHATBI_TASK_STATUS_PENDING,
    CHATBI_TASK_STATUS_RUNNING,
    CHATBI_TASK_STATUS_SUCCESS,
)


class TaskType(StrEnum):
    """预处理与表格导入类异步任务类型。"""

    PREPROCESS_SCHEMA = "PREPROCESS_SCHEMA"
    FILE_UPLOAD_IMPORT_AND_SCHEMA = "FILE_UPLOAD_IMPORT_AND_SCHEMA"


class TaskStatus(StrEnum):
    """任务执行生命周期状态。"""

    PENDING = CHATBI_TASK_STATUS_PENDING
    RUNNING = CHATBI_TASK_STATUS_RUNNING
    SUCCESS = CHATBI_TASK_STATUS_SUCCESS
    FAILED = CHATBI_TASK_STATUS_FAILED


ACTIVE_TASK_STATUSES = CHATBI_ACTIVE_TASK_STATUSES


@dataclass(slots=True)
class ChatbiTaskRecord:
    """任务执行所需的只读领域记录。"""

    id: int
    task_type: str
    status: str
    datasource_id: int
    total_count: int
    processed_count: int
    payload: dict[str, Any]
    last_error: str | None
    created_by: int | None


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "ChatbiTaskRecord",
    "TaskStatus",
    "TaskType",
]
