#!/usr/bin/env python3
"""Show which datasources are present in chatbi_value_index."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select, text
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
    from app.models.system.chatbi import ChatbiDatasource

    value_index_url = (
        os.environ.get("CHATBI_KNOWLEDGE_DATABASE_URL")
        or os.environ.get("CHATBI_MULTI_AGENT_KNOWLEDGE_DATABASE_URL")
    )
    if not value_index_url:
        raise RuntimeError("CHATBI_KNOWLEDGE_DATABASE_URL is not configured")

    engine = create_async_engine(value_index_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT datasource_id, count(*) AS row_count
                        FROM chatbi_value_index
                        GROUP BY datasource_id
                        ORDER BY datasource_id
                        """
                    )
                )
            ).all()
    finally:
        await engine.dispose()

    datasource_ids = [int(row.datasource_id) for row in rows]
    database = get_default_database()
    database.initialize()
    try:
        async with database.get_session() as session:
            names = {}
            if datasource_ids:
                name_rows = await session.execute(
                    select(ChatbiDatasource.id, ChatbiDatasource.name).where(
                        ChatbiDatasource.id.in_(datasource_ids)
                    )
                )
                names = {int(row.id): str(row.name) for row in name_rows}
    finally:
        await database.dispose()

    total_rows = 0
    non_bird = 0
    for row in rows:
        datasource_id = int(row.datasource_id)
        row_count = int(row.row_count)
        total_rows += row_count
        name = names.get(datasource_id, "<missing>")
        if not name.startswith("BIRD-DEV"):
            non_bird += 1
        print(f"{datasource_id}\t{row_count}\t{name}")
    print(
        f"TOTAL_ROWS={total_rows} INDEXED_DATASOURCES={len(rows)} NON_BIRD_DEV={non_bird}"
    )


if __name__ == "__main__":
    asyncio.run(_main())
