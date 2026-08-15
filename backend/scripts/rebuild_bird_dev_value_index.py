#!/usr/bin/env python3
"""Clear value index and rebuild it only for BIRD-DEV datasources."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

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


async def _clear_value_index(database_url: str) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE chatbi_value_index"))
    finally:
        await engine.dispose()


async def _count_value_index(database_url: str) -> tuple[int, int]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows = int((await conn.execute(text("SELECT count(*) FROM chatbi_value_index"))).scalar_one() or 0)
            datasources = int(
                (
                    await conn.execute(
                        text("SELECT count(DISTINCT datasource_id) FROM chatbi_value_index")
                    )
                ).scalar_one()
                or 0
            )
            return rows, datasources
    finally:
        await engine.dispose()


async def _main() -> int:
    _load_env()

    from app.core.config import settings
    from app.core.database import get_default_database
    from app.domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
    from app.models.system.chatbi import ChatbiDatasource
    from app.repositories.system.chatbi import ChatbiDatasourceRepository
    from app.services.system.chatbi.datasource.credential_encryption_service import (
        ChatbiCredentialEncryptionService,
    )
    from app.services.system.chatbi.datasource.db_connection_service import ChatbiDbConnectionService
    from app.services.system.chatbi.value_index import ChatbiColumnProfiler, ChatbiValueIndexStore

    value_index_url = (
        os.environ.get("CHATBI_KNOWLEDGE_DATABASE_URL")
        or os.environ.get("CHATBI_MULTI_AGENT_KNOWLEDGE_DATABASE_URL")
    )
    if not value_index_url:
        raise RuntimeError("CHATBI_KNOWLEDGE_DATABASE_URL is not configured")

    print("[bird-dev-index] clearing chatbi_value_index", flush=True)
    await _clear_value_index(value_index_url)

    database = get_default_database()
    database.initialize()
    ok = 0
    failed: list[tuple[int, str, str]] = []
    try:
        async with database.get_session() as session:
            result = await session.execute(
                select(
                    ChatbiDatasource.id,
                    ChatbiDatasource.name,
                    ChatbiDatasource.created_by,
                    ChatbiDatasource.db_schema,
                )
                .where(
                    ChatbiDatasource.is_deleted.is_(False),
                    ChatbiDatasource.name.like("BIRD-DEV%"),
                )
                .order_by(ChatbiDatasource.name.asc(), ChatbiDatasource.id.asc())
            )
            datasources = list(result.mappings().all())
            print(f"[bird-dev-index] found {len(datasources)} BIRD-DEV datasource(s)", flush=True)

            ds_repo = ChatbiDatasourceRepository(session)
            db_conn = ChatbiDbConnectionService(
                datasource_repo=ds_repo,
                encryption=ChatbiCredentialEncryptionService(
                    key_material=settings.chatbi_datasource_credential_encryption_key,
                ),
            )
            index_store = ChatbiValueIndexStore()

            for index, row in enumerate(datasources, start=1):
                datasource_id = int(row["id"])
                name = str(row["name"])
                user_id = int(row["created_by"] or 0)
                print(
                    f"[bird-dev-index] ({index}/{len(datasources)}) datasource_id={datasource_id} name={name!r}",
                    flush=True,
                )
                try:
                    db_schema_payload = row["db_schema"]
                    if not isinstance(db_schema_payload, dict):
                        raise RuntimeError("db_schema is empty or invalid")
                    schema = ChatbiDbSchemaRecord.from_json_dict(db_schema_payload)

                    async def execute_sql(
                        sql: str,
                        max_rows: int,
                        timeout_seconds: float,
                    ) -> tuple[list[str], list[dict[str, Any]], bool]:
                        return await db_conn.execute_readonly_sql(
                            datasource_id=datasource_id,
                            user_id=user_id,
                            sql=sql,
                            max_rows=max_rows,
                            timeout_seconds=timeout_seconds,
                        )

                    profiles = await ChatbiColumnProfiler(execute_sql).profile_schema(schema)
                    await index_store.rebuild_datasource(
                        datasource_id=datasource_id,
                        db_name=schema.database,
                        profiles=profiles,
                    )
                    ok += 1
                    rows, indexed_datasources = await _count_value_index(value_index_url)
                    print(
                        "[bird-dev-index] success "
                        f"datasource_id={datasource_id} total_rows={rows} "
                        f"indexed_datasources={indexed_datasources}",
                        flush=True,
                    )
                except Exception as exc:
                    failed.append((datasource_id, name, str(exc)))
                    print(
                        f"[bird-dev-index] failed datasource_id={datasource_id} name={name!r}: {exc}",
                        flush=True,
                    )
    finally:
        await database.dispose()

    rows, indexed_datasources = await _count_value_index(value_index_url)
    print(
        "[bird-dev-index] done "
        f"success={ok} failed={len(failed)} rows={rows} indexed_datasources={indexed_datasources}",
        flush=True,
    )
    for datasource_id, name, message in failed:
        print(
            f"[bird-dev-index] FAILED datasource_id={datasource_id} name={name!r} error={message}",
            flush=True,
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
