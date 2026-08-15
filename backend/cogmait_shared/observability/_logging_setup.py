"""logging.setup 私有配置工具。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_TRUE_BOOL_TEXTS = {"1", "true", "yes", "on"}
_FALSE_BOOL_TEXTS = {"0", "false", "no", "off", ""}


@dataclass(slots=True, frozen=True)
class _ResolvedLoggingOptions:
    level: str | int
    log_path_template: str
    diagnose_enabled: bool
    serialize_enabled: bool
    stdout_enabled: bool
    colorize_enabled: bool


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bytes | bytearray):
        try:
            value = value.decode()
        except UnicodeDecodeError:
            return default
    if isinstance(value, str) and not value.strip():
        return default
    parsed = _parse_strict_bool(value)
    if parsed is None:
        return default
    return parsed


def _parse_strict_bool(raw_value: Any) -> bool | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int):
        if raw_value in {0, 1}:
            return bool(raw_value)
        return None
    if isinstance(raw_value, bytes | bytearray):
        try:
            raw_value = raw_value.decode()
        except UnicodeDecodeError:
            return None
    if not isinstance(raw_value, str):
        return None
    normalized = raw_value.strip().lower()
    if normalized in _TRUE_BOOL_TEXTS:
        return True
    if normalized in _FALSE_BOOL_TEXTS:
        return False
    return None


def _resolve_level(level: str | int | None) -> str | int:
    if isinstance(level, bool):
        raise ValueError("level 必须为整数或字符串")
    if isinstance(level, int):
        return level

    env_level = os.getenv("LOG_LEVEL") or os.getenv("COGMAIT_LOG_LEVEL")
    raw_level = level if level is not None else env_level
    normalized = str(raw_level or "INFO").strip()
    if not normalized:
        return "INFO"
    if normalized.lstrip("+-").isdigit():
        return int(normalized)
    return normalized.upper()


def _resolve_bool_option(
    explicit: bool | None,
    *,
    env_name: str,
    default: bool,
) -> bool:
    return _as_bool(explicit, default=_as_bool(os.getenv(env_name), default))


def _resolve_base_dir(base_dir: str | Path | None) -> Path:
    configured = (
        base_dir
        or os.getenv("COGMAIT_LOG_DIR")
        or os.getenv("LOG_BASE_DIR")
        or os.getenv("LOG_DIR")
        or "logs"
    )
    resolved = Path(configured).expanduser()
    resolved.mkdir(parents=True, exist_ok=True)
    month_dir = resolved / datetime.now().strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    return resolved


def _resolve_log_path_template(
    *,
    base_dir: Path,
    path_template: str | Path | None,
) -> str:
    if path_template is None:
        return (base_dir / "{time:YYYY-MM}" / "{time:YYYY-MM-DD}.log").as_posix()

    normalized = str(path_template).strip()
    if not normalized:
        raise ValueError("服务级日志模板不能为空")

    expanded = Path(normalized).expanduser()

    def _contains_template_token(path: Path) -> bool:
        path_text = path.as_posix()
        return "{" in path_text or "}" in path_text

    prefix = normalized.split("{", 1)[0]
    if prefix:
        prefix_path = Path(prefix).expanduser()
        directory = prefix_path if prefix.endswith(("/", "\\")) else prefix_path.parent
        if str(directory) not in ("", ".") and not _contains_template_token(directory):
            directory.mkdir(parents=True, exist_ok=True)
    else:
        parent_dir = expanded.parent
        if str(parent_dir) not in ("", ".") and not _contains_template_token(parent_dir):
            parent_dir.mkdir(parents=True, exist_ok=True)
    return expanded.as_posix()


def _resolve_setup_options(
    *,
    level: str | int | None,
    base_dir: str | Path | None,
    path_template: str | Path | None,
    diagnose: bool | None,
    serialize: bool | None,
    stdout: bool | None,
    colorize: bool | None,
) -> _ResolvedLoggingOptions:
    resolved_level = _resolve_level(level)
    resolved_dir = _resolve_base_dir(base_dir)
    diagnose_enabled = _resolve_bool_option(diagnose, env_name="LOG_DIAGNOSE", default=False)
    serialize_enabled = _resolve_bool_option(serialize, env_name="LOG_SERIALIZE", default=False)
    stdout_enabled = _resolve_bool_option(stdout, env_name="LOG_STDOUT", default=True)
    colorize_enabled = _resolve_bool_option(
        colorize,
        env_name="LOG_COLORIZE",
        default=sys.stdout.isatty(),
    )
    log_path_template = _resolve_log_path_template(
        base_dir=resolved_dir,
        path_template=path_template,
    )
    return _ResolvedLoggingOptions(
        level=resolved_level,
        log_path_template=log_path_template,
        diagnose_enabled=diagnose_enabled,
        serialize_enabled=serialize_enabled,
        stdout_enabled=stdout_enabled,
        colorize_enabled=colorize_enabled,
    )


def _build_file_sink_params(
    *,
    options: _ResolvedLoggingOptions,
    rotation: Any,
    retention: Any,
    enqueue: bool,
    format: str,
) -> dict[str, Any]:
    return {
        "level": options.level,
        "rotation": rotation,
        "retention": retention,
        "enqueue": enqueue,
        "backtrace": options.diagnose_enabled,
        "diagnose": options.diagnose_enabled,
        "format": format,
        "encoding": "utf-8",
        "serialize": options.serialize_enabled,
    }


def _build_stdout_sink_params(
    *,
    options: _ResolvedLoggingOptions,
    enqueue: bool,
    format: str,
) -> dict[str, Any]:
    return {
        "level": options.level,
        "format": format,
        "backtrace": options.diagnose_enabled,
        "diagnose": options.diagnose_enabled,
        "colorize": options.colorize_enabled,
        "enqueue": enqueue,
        "serialize": False,
    }
