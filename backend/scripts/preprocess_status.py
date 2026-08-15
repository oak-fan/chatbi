#!/usr/bin/env python3
"""Print ChatBI datasource preprocessing status."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

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
    from app.models.system.chatbi import ChatbiDatasource, ChatbiTask

    database = get_default_database()
    database.initialize()
    async with database.get_session() as session:
        datasource_total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ChatbiDatasource)
                    .where(ChatbiDatasource.is_deleted.is_(False))
                )
            ).scalar_one()
            or 0
        )
        schema_ready = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ChatbiDatasource)
                    .where(
                        ChatbiDatasource.is_deleted.is_(False),
                        ChatbiDatasource.db_schema.is_not(None),
                    )
                )
            ).scalar_one()
            or 0
        )
        print(f"datasources: total={datasource_total} schema_ready={schema_ready}")

        status_rows = await session.execute(
            select(ChatbiTask.status, func.count())
            .where(ChatbiTask.is_deleted.is_(False))
            .group_by(ChatbiTask.status)
            .order_by(ChatbiTask.status)
        )
        print("task_status:")
        for status, count in status_rows:
            print(f"  {status}: {int(count)}")

        recent_rows = await session.execute(
            select(
                ChatbiTask.id,
                ChatbiTask.datasource_id,
                ChatbiTask.status,
                ChatbiTask.last_error,
            )
            .where(ChatbiTask.is_deleted.is_(False))
            .order_by(ChatbiTask.updated_at.desc(), ChatbiTask.id.desc())
            .limit(12)
        )
        print("recent_tasks:")
        for task_id, datasource_id, status, last_error in recent_rows:
            err = str(last_error or "").replace("\n", " ")[:180]
            print(f"  id={int(task_id)} ds={int(datasource_id)} status={status} error={err}")

        latest_subquery = (
            select(
                ChatbiTask.datasource_id,
                func.max(ChatbiTask.id).label("latest_task_id"),
            )
            .where(ChatbiTask.is_deleted.is_(False))
            .group_by(ChatbiTask.datasource_id)
            .subquery()
        )
        latest_rows = await session.execute(
            select(
                ChatbiDatasource.id,
                ChatbiDatasource.name,
                ChatbiTask.status,
                ChatbiTask.last_error,
            )
            .outerjoin(latest_subquery, latest_subquery.c.datasource_id == ChatbiDatasource.id)
            .outerjoin(ChatbiTask, ChatbiTask.id == latest_subquery.c.latest_task_id)
            .where(ChatbiDatasource.is_deleted.is_(False))
            .order_by(ChatbiDatasource.id.asc())
        )
        print("latest_by_datasource:")
        for datasource_id, name, status, last_error in latest_rows:
            err = str(last_error or "").replace("\n", " ")[:120]
            print(f"  ds={int(datasource_id)} name={name!r} status={status or 'none'} error={err}")

    value_index_url = (
        os.environ.get("CHATBI_KNOWLEDGE_DATABASE_URL")
        or os.environ.get("CHATBI_MULTI_AGENT_KNOWLEDGE_DATABASE_URL")
    )
    try:
        if not value_index_url:
            raise RuntimeError("CHATBI_KNOWLEDGE_DATABASE_URL is not configured")
        engine = create_async_engine(value_index_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            count_result = await conn.execute(text("select count(*) from chatbi_value_index"))
            ds_result = await conn.execute(
                text("select count(distinct datasource_id) from chatbi_value_index")
            )
            print(
                "value_index: "
                f"rows={int(count_result.scalar_one() or 0)} "
                f"datasources={int(ds_result.scalar_one() or 0)}"
            )
    except Exception as exc:
        print(f"value_index: unavailable error={exc}")
    await database.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
