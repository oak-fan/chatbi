#!/usr/bin/env python3
"""cogmait-chatbi 本地服务启动入口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
SHARED = ROOT.parent / "cogmait-backend-v2" / "shared"


def _load_env() -> None:
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if name == ".env.local":
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)


def _extend_sys_path() -> None:
    preferred = [str(ROOT), str(SHARED)]
    existing = [p for p in sys.path if p not in preferred]
    sys.path[:] = preferred + existing
    pythonpath = os.environ.get("PYTHONPATH", "")
    merged = os.pathsep.join(preferred + ([pythonpath] if pythonpath else []))
    os.environ["PYTHONPATH"] = merged


def main() -> None:
    _extend_sys_path()
    _load_env()
    os.chdir(ROOT)

    from app.core.config import settings

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
