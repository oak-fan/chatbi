#!/usr/bin/env python3
"""cogmait-chatbi Worker 启动入口。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED = ROOT.parent / "cogmait-backend-v2" / "shared"


@dataclass(slots=True)
class WorkerSpec:
    module: str
    count: int = 1
    args_template: list[str] = field(default_factory=list)


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
            if name == ".env":
                os.environ.setdefault(key, value)
            else:
                os.environ[key] = value


def _extend_sys_path() -> None:
    preferred = [str(ROOT), str(SHARED)]
    pythonpath = os.environ.get("PYTHONPATH", "")
    merged = os.pathsep.join(preferred + ([pythonpath] if pythonpath else []))
    os.environ["PYTHONPATH"] = merged


def _load_workers(config_path: Path) -> list[WorkerSpec]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    specs: list[WorkerSpec] = []
    for item in payload.get("workers", []):
        specs.append(
            WorkerSpec(
                module=str(item["module"]),
                count=int(item.get("count", 1)),
                args_template=list(item.get("args_template", [])),
            )
        )
    return specs


def _spawn_worker(spec: WorkerSpec, index: int) -> subprocess.Popen[str]:
    args = [sys.executable, "-m", spec.module, *spec.args_template]
    env = os.environ.copy()
    print(f"[worker] starting {spec.module} #{index + 1}: {' '.join(args)}")
    return subprocess.Popen(args, env=env)  # nosec B603


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 cogmait-chatbi workers")
    parser.add_argument(
        "--config",
        default=str(ROOT / "workers.json"),
        help="Worker 配置文件路径",
    )
    args = parser.parse_args()

    _extend_sys_path()
    _load_env()
    os.chdir(ROOT)

    specs = _load_workers(Path(args.config))
    processes: list[subprocess.Popen[str]] = []
    for spec in specs:
        for index in range(spec.count):
            processes.append(_spawn_worker(spec, index))

    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    raise SystemExit(f"worker exited with code {code}")
            time.sleep(1)
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()


if __name__ == "__main__":
    main()
