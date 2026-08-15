"""临时文件路径工具。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from .utils import sanitize_filename

__all__ = ["TempFileStore"]


class TempFileStore:
    """将临时文件集中到指定目录，提供路径与目录创建能力。"""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        """初始化临时目录根路径并确保目录存在。"""
        resolved_base = Path(base_dir) if base_dir else self._default_base_dir()
        self.base_dir = resolved_base
        self._base_dir_resolved = self.base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def build_file_path(
        self,
        *,
        filename: str | None = None,
        subdir: str | Path | None = None,
        suffix: str | None = None,
    ) -> Path:
        """生成位于临时目录内的文件绝对路径，并确保父目录存在。"""
        target_dir = self._resolve_target_dir(subdir)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._build_safe_name(filename=filename, suffix=suffix)
        return target_dir / safe_name

    def create_dir(
        self,
        *,
        dirname: str | None = None,
        subdir: str | Path | None = None,
        prefix: str = "tmp-",
    ) -> Path:
        """创建位于临时目录内的子目录并返回绝对路径。"""
        target_dir = self._resolve_target_dir(subdir)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_dirname = sanitize_filename(dirname) if dirname else f"{prefix}{uuid4().hex}"
        created_dir = target_dir / safe_dirname
        created_dir.mkdir(parents=True, exist_ok=True)
        return created_dir

    def _resolve_target_dir(self, subdir: str | Path | None) -> Path:
        if subdir is None:
            return self._base_dir_resolved
        target_dir = Path(subdir)
        if target_dir.is_absolute():
            raise ValueError("subdir must be relative to base_dir")
        resolved = (self.base_dir / target_dir).resolve()
        try:
            resolved.relative_to(self._base_dir_resolved)
        except ValueError as exc:
            raise ValueError("subdir is outside base_dir") from exc
        return resolved

    @staticmethod
    def _build_safe_name(*, filename: str | None, suffix: str | None) -> str:
        resolved_suffix = ""
        if suffix:
            resolved_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return (
            sanitize_filename(filename) if filename else f"{uuid4().hex}{resolved_suffix or '.tmp'}"
        )

    @staticmethod
    def _default_base_dir() -> Path:
        """确定默认临时目录：优先环境变量，其次仓库根目录，再退回系统 temp。"""
        env_dir = os.getenv("FILE_TEMP_DIR")
        if env_dir:
            return Path(env_dir)
        try:
            repo_root = Path(__file__).resolve().parents[3]
            return repo_root / "tmp" / "file_temp"
        except (IndexError, OSError):
            return Path(tempfile.gettempdir()) / "file_temp"
