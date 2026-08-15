"""ai_service 日志初始化模块。"""

from cogmait_shared.observability.logging import (
    LoggingManagerOptions,
    configure_custom_logging,
    logger,
)

from .config import settings


def init_logging() -> None:
    configure_custom_logging(
        LoggingManagerOptions(
            level=settings.log_level,
            base_dir=settings.log_dir,
            path_template=settings.log_path_template,
        )
    )


__all__ = ["logger", "init_logging"]
