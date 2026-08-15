"""ai_service 的 Alembic 运行环境配置。"""

# ruff: noqa: I001

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.models.system import *  # noqa: F403
from cogmait_shared.db import Base as AIBase

config: Any = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = AIBase.metadata
MANAGED_TABLES = set(AIBase.metadata.tables.keys())
VERSION_TABLE = config.get_main_option("version_table") or "alembic_version_cogmait_chatbi"


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """仅管理 ai_service 自身表。"""

    if type_ == "table":
        return name in MANAGED_TABLES

    table = getattr(object_, "table", None)
    if table is not None:
        return table.name in MANAGED_TABLES

    return True


def run_migrations_offline() -> None:
    """离线模式执行迁移。"""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        version_table=VERSION_TABLE,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在已建立连接上执行迁移。"""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        version_table=VERSION_TABLE,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式执行迁移。"""

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    import asyncio

    async def _run() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()

    asyncio.run(_run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
