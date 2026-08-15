#!/usr/bin/env python3
"""Mark active non-BIRD-DEV preprocess tasks failed after scoped value-index rebuild."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select, update

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


async def _main() -> None:
    _load_env()

    from app.core.database import get_default_database
    from app.domain.system.chatbi import ACTIVE_TASK_STATUSES, TaskStatus
    from app.models.system.chatbi import ChatbiDatasource, ChatbiTask

    database = get_default_database()
    database.initialize()
    try:
        async with database.get_session() as session:
            active_rows = (
                await session.execute(
                    select(ChatbiTask.id, ChatbiTask.datasource_id, ChatbiDatasource.name)
                    .join(ChatbiDatasource, ChatbiDatasource.id == ChatbiTask.datasource_id)
                    .where(
                        ChatbiTask.is_deleted.is_(False),
                        ChatbiTask.status.in_(ACTIVE_TASK_STATUSES),
                        ChatbiDatasource.is_deleted.is_(False),
                        ~ChatbiDatasource.name.like("BIRD-DEV%"),
                    )
                    .order_by(ChatbiTask.id.asc())
                )
            ).all()
            task_ids = [int(row.id) for row in active_rows]
            if task_ids:
                await session.execute(
                    update(ChatbiTask)
                    .where(ChatbiTask.id.in_(task_ids))
                    .values(
                        status=TaskStatus.FAILED.value,
                        last_error="Stopped to keep chatbi_value_index scoped to BIRD-DEV datasources.",
                    )
                )
                await session.commit()
            for row in active_rows:
                print(f"marked_failed task_id={int(row.id)} ds={int(row.datasource_id)} name={row.name}")
            print(f"marked_count={len(task_ids)}")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
