#!/usr/bin/env python3
"""Run ChatBI preprocessing for every active datasource once.

This maintenance script intentionally bypasses Redis publishing while reusing
the normal ChatbiDatasourceService task processor.
"""

from __future__ import annotations

import asyncio
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "cogmait-backend-v2" / "shared"
for path in (ROOT, SHARED):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


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
            if name == ".env":
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
            else:
                os.environ[key.strip()] = value.strip().strip("\"'")


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-without-task", action="store_true")
    parser.add_argument("--log-file", default="")
    args = parser.parse_args()

    log_path = Path(args.log_file).resolve() if args.log_file else None

    def emit(message: str) -> None:
        print(message, flush=True)
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")

    _load_env()

    from cogmait_shared.db import UnitOfWork

    from app.core.config import settings
    from app.core.database import get_default_database
    from app.core.redis import get_redis_client
    from app.domain.system.chatbi import ACTIVE_TASK_STATUSES, TaskType
    from app.models.system.chatbi import ChatbiDatasource, ChatbiTask
    from app.repositories.system.chatbi.task import ChatbiTaskRepository
    from app.services.system.chatbi.datasource_service import ChatbiDatasourceService
    from app.services.system.chatbi.vector import (
        build_chatbi_vector_settings,
        initialize_chatbi_vector_backend,
    )
    from app.services.system.content_extract import FileAccessService
    from app.services.system.llm_service import get_default_llm_service

    database = get_default_database()
    database.initialize()
    initialize_chatbi_vector_backend(build_chatbi_vector_settings(settings))
    redis = get_redis_client()

    async with database.get_session() as session:
        result = await session.execute(
            select(ChatbiDatasource.id, ChatbiDatasource.name, ChatbiDatasource.created_by)
            .where(ChatbiDatasource.is_deleted.is_(False))
            .order_by(ChatbiDatasource.id.asc())
        )
        datasources = [(int(row.id), str(row.name), int(row.created_by or 0)) for row in result]
        if args.only_without_task:
            task_result = await session.execute(
                select(ChatbiTask.datasource_id).where(ChatbiTask.is_deleted.is_(False))
            )
            datasource_ids_with_task = {int(row.datasource_id) for row in task_result}
            datasources = [
                item for item in datasources if item[0] not in datasource_ids_with_task
            ]

    total = len(datasources)
    mode = "without existing task" if args.only_without_task else "active"
    emit(f"[preprocess-all] found {total} {mode} datasource(s)")
    ok = 0
    failed: list[tuple[int, str, str]] = []

    for index, (datasource_id, name, user_id) in enumerate(datasources, start=1):
        emit(f"[preprocess-all] ({index}/{total}) datasource_id={datasource_id} name={name!r}")
        async with database.get_session() as session:
            file_access = FileAccessService()
            task_id: int | None = None
            try:
                uow = UnitOfWork(session)
                service = ChatbiDatasourceService(
                    unit_of_work=uow,
                    redis=redis,
                    file_access_service=file_access,
                    llm_service=get_default_llm_service(),
                )
                active_result = await session.execute(
                    select(ChatbiTask.id)
                    .where(
                        ChatbiTask.datasource_id == datasource_id,
                        ChatbiTask.is_deleted.is_(False),
                        ChatbiTask.status.in_(ACTIVE_TASK_STATUSES),
                    )
                    .order_by(ChatbiTask.updated_at.desc(), ChatbiTask.id.desc())
                    .limit(1)
                )
                active_task_id = active_result.scalar_one_or_none()
                if active_task_id is None:
                    task_id = await ChatbiTaskRepository(session).create_task(
                        datasource_id=datasource_id,
                        task_type=TaskType.PREPROCESS_SCHEMA.value,
                        user_id=user_id,
                    )
                    await uow.commit()
                else:
                    task_id = int(active_task_id)
                    emit(f"[preprocess-all] using existing active task_id={task_id}")

                await service.process_preprocess_task(task_id)
                status_result = await session.execute(
                    select(ChatbiTask.status, ChatbiTask.last_error).where(ChatbiTask.id == task_id)
                )
                row = status_result.one()
                status = str(row.status)
                if status.upper() == "SUCCESS":
                    ok += 1
                    emit(f"[preprocess-all] success task_id={task_id}")
                else:
                    message = str(row.last_error or f"status={status}")
                    failed.append((datasource_id, name, message))
                    emit(
                        f"[preprocess-all] failed task_id={task_id} "
                        f"datasource_id={datasource_id}: {message}"
                    )
            except Exception as exc:
                failed.append((datasource_id, name, str(exc)))
                emit(
                    f"[preprocess-all] exception datasource_id={datasource_id} "
                    f"task_id={task_id}: {exc}"
                )
            finally:
                await file_access.aclose()

    emit(f"[preprocess-all] done success={ok} failed={len(failed)} total={total}")
    for datasource_id, name, message in failed:
        emit(f"[preprocess-all] FAILED datasource_id={datasource_id} name={name!r} error={message}")

    await redis.aclose()
    await database.dispose()
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
