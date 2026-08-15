"""FastAPI 导入别名，避免本包内同名模块影响类型检查。"""

from __future__ import annotations

import importlib
from typing import Any

_fastapi: Any = importlib.import_module("fastapi")

Depends = _fastapi.Depends
Header = _fastapi.Header
HTTPException = _fastapi.HTTPException

__all__ = ["Depends", "Header", "HTTPException"]
