"""CogmAIT 日志工具。

提供一个统一的入口使用 Loguru 配置日志，将日志输出到控制台以及按
``logs/<YYYY-MM>/<YYYY-MM-DD>.log`` 结构存储的文件中，满足“按月分文件夹、
按日分文件”的需求。
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, cast

from loguru import logger as _loguru_logger

from . import _logging_setup
from .request_id import (
    ensure_request_id,
    get_request_id,
    normalize_request_id,
    request_id_context,
    reset_request_id,
    set_request_id,
)

__all__ = [
    "setup_logging",
    "route_std_loggers_to_root",
    "configure_custom_logging",
    "LoggingManager",
    "LoggingManagerOptions",
    "logger",
    "InterceptHandler",
    "set_request_id",
    "get_request_id",
    "normalize_request_id",
    "reset_request_id",
    "ensure_request_id",
    "request_id_context",
]

logger: Any = _loguru_logger

# 默认日志格式：时间 | 级别 | 来源 | 消息
DEFAULT_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
    "rid={extra[request_id]:<36} | "
    "{name}:{function}:{line} - {message}"
)

_ResolvedLoggingOptions = _logging_setup._ResolvedLoggingOptions
_build_file_sink_params = _logging_setup._build_file_sink_params
_build_stdout_sink_params = _logging_setup._build_stdout_sink_params
_resolve_bool_option = _logging_setup._resolve_bool_option
_resolve_level = _logging_setup._resolve_level
_resolve_log_path_template = _logging_setup._resolve_log_path_template
_resolve_setup_options = _logging_setup._resolve_setup_options


@dataclass(slots=True, frozen=True)
class LoggingManagerOptions:
    """自定义日志管理参数。"""

    level: str | int | None = None
    base_dir: str | Path | None = None
    path_template: str | Path | None = None
    rotation: Any = "00:00"
    retention: Any = "30 days"
    diagnose: bool | None = None
    serialize: bool | None = None
    format: str = DEFAULT_FORMAT
    stdout: bool | None = None
    colorize: bool | None = None
    enqueue: bool = True
    patch_logging: bool = True
    extra_sinks: Iterable[tuple[Any, dict[str, Any]]] | None = None


class LoggingManager:
    """统一封装日志初始化，作为默认自定义日志管理入口。"""

    def __init__(self, options: LoggingManagerOptions) -> None:
        self._options = options

    def configure(self) -> None:
        options = self._options
        setup_logging(
            level=options.level,
            base_dir=options.base_dir,
            path_template=options.path_template,
            rotation=options.rotation,
            retention=options.retention,
            diagnose=options.diagnose,
            serialize=options.serialize,
            format=options.format,
            stdout=options.stdout,
            colorize=options.colorize,
            enqueue=options.enqueue,
            patch_logging=options.patch_logging,
            extra_sinks=options.extra_sinks,
        )


class InterceptHandler(logging.Handler):
    """将标准 logging 日志转发给 Loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: int | str = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame: FrameType | None = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


def _configure_std_logging(level: str | int) -> None:
    numeric_level: int
    if isinstance(level, int):
        numeric_level = level
    else:
        resolved = logging.getLevelName(str(level).upper())
        numeric_level = resolved if isinstance(resolved, int) else logging.INFO

    handler = InterceptHandler()
    logging.root.handlers = [handler]
    logging.root.setLevel(numeric_level)

    for logger_name in list(logging.root.manager.loggerDict.keys()):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = []
        logging_logger.propagate = True


def route_std_loggers_to_root(*logger_names: str) -> None:
    """移除指定标准库 logger 的自有 handlers，使其走统一 root 转发。"""

    for logger_name in logger_names:
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = []
        logging_logger.propagate = True


def _patch_record(record: MutableMapping[str, Any]) -> None:
    """在 Loguru 日志记录中注入 request_id。"""
    record.setdefault("extra", {})
    record["extra"]["request_id"] = get_request_id()


def _configure_extra_sinks(extra_sinks: Iterable[tuple[Any, dict[str, Any]]] | None) -> None:
    if not extra_sinks:
        return
    for sink, kwargs in extra_sinks:
        logger.add(sink, **kwargs)


def _configure_default_sinks(
    *,
    options: _ResolvedLoggingOptions,
    rotation: Any,
    retention: Any,
    enqueue: bool,
    format: str,
) -> None:
    file_sink_params = _build_file_sink_params(
        options=options,
        rotation=rotation,
        retention=retention,
        enqueue=enqueue,
        format=format,
    )
    logger.add(options.log_path_template, **file_sink_params)

    if not options.stdout_enabled:
        return
    stdout_params = _build_stdout_sink_params(
        options=options,
        enqueue=enqueue,
        format=format,
    )
    logger.add(sys.stdout, **stdout_params)


def _configure_std_logging_if_needed(*, enabled: bool, level: str | int) -> None:
    if enabled:
        _configure_std_logging(level)


def setup_logging(
    *,
    level: str | int | None = None,
    base_dir: str | Path | None = None,
    path_template: str | Path | None = None,
    rotation: Any = "00:00",  # 每日 00:00 轮转
    retention: Any = "30 days",
    diagnose: bool | None = None,
    serialize: bool | None = None,
    format: str = DEFAULT_FORMAT,
    stdout: bool | None = None,
    colorize: bool | None = None,
    enqueue: bool = True,
    patch_logging: bool = True,
    extra_sinks: Iterable[tuple[Any, dict[str, Any]]] | None = None,
) -> None:
    """配置 Loguru 日志。

    参数:
        level: 输出日志级别，默认取环境变量 ``LOG_LEVEL``/``COGMAIT_LOG_LEVEL``。
        base_dir: 日志目录，默认为 ``logs`` 或相关环境变量指定的目录。
        path_template: 日志文件模板路径（例如
            ``/data/logs/{time:YYYY-MM}/app-{time:YYYY-MM-DD}.log``）。
        rotation: Loguru ``rotation`` 参数，默认每天 00:00。
        retention: Loguru ``retention`` 参数，默认保留 30 天。
        diagnose: 是否启用 Loguru diagnose，默认根据环境变量 ``LOG_DIAGNOSE``。
        serialize: 是否输出 JSON，默认根据 ``LOG_SERIALIZE``。
        format: 日志格式字符串。
        stdout: 是否输出到标准输出，优先读取 ``LOG_STDOUT``。
        colorize: 是否彩色输出，优先读取 ``LOG_COLORIZE``（默认依据终端 TTY）。
        enqueue: 是否使用队列异步写入。
        patch_logging: 是否接管标准库 logging。
        extra_sinks: 额外的 sink 配置，序列中每个元素形如 ``(sink, kwargs)``。
    """
    options = _resolve_setup_options(
        level=level,
        base_dir=base_dir,
        path_template=path_template,
        diagnose=diagnose,
        serialize=serialize,
        stdout=stdout,
        colorize=colorize,
    )

    logger.remove()
    logger.configure(patcher=cast("Callable[[object], None]", _patch_record))
    _configure_default_sinks(
        options=options,
        rotation=rotation,
        retention=retention,
        enqueue=enqueue,
        format=format,
    )

    _configure_extra_sinks(extra_sinks)
    _configure_std_logging_if_needed(enabled=patch_logging, level=options.level)


def configure_custom_logging(options: LoggingManagerOptions) -> None:
    """默认自定义日志管理入口。"""
    LoggingManager(options).configure()
