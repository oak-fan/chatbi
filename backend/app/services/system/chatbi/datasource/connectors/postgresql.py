"""PostgreSQL 数据源连接器实现。"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote_plus, urlencode

import asyncpg

from ......constants.chatbi.datasource import (
    CHATBI_DEFAULT_SCHEMA_NAME,
    CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS,
    CHATBI_STRUCTURE_LOAD_TIMEOUT_SECONDS,
    CHATBI_STRUCTURE_SAMPLE_COLUMN_LIMIT,
    CHATBI_STRUCTURE_SAMPLE_TABLE_LIMIT,
    CHATBI_STRUCTURE_SAMPLE_TIMEOUT_SECONDS,
)
from ......domain.system.chatbi.db_schema import (
    ChatbiDbSchemaColumnRecord,
    ChatbiDbSchemaForeignKeyRecord,
    ChatbiDbSchemaForeignKeyRefRecord,
    ChatbiDbSchemaRecord,
    ChatbiDbSchemaTableRecord,
)
from .base import BaseDatasourceConnector
from .exceptions import ConnectionTestError

_ALLOWED_READONLY_START = {"select", "with"}
_FORBIDDEN_READONLY_KEYWORDS = re.compile(
    r"\b("
    r"insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"call|execute|copy|vacuum|analyze|refresh|listen|notify|set|reset|into"
    r")\b",
    flags=re.IGNORECASE,
)
_SQL_COMMENT_PATTERN = re.compile(r"(--[^\n\r]*|/\*.*?\*/)", flags=re.DOTALL)
_SQL_LITERAL_PATTERN = re.compile(
    r"('([^']|'')*'|\"([^\"]|\"\")*\"|\$[A-Za-z0-9_]*\$.*?\$[A-Za-z0-9_]*\$)",
    flags=re.DOTALL,
)
_ALLOWED_DSN_PARAMS = frozenset(
    {
        "application_name",
        "options",
        "sslmode",
        "target_session_attrs",
    }
)
_ALLOWED_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})


def _extra_params(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("extra_params")
    return dict(raw) if isinstance(raw, dict) else {}


def _dsn_query(config: dict[str, Any]) -> str:
    params: dict[str, str] = {}
    raw_params = _extra_params(config)
    for key in sorted(_ALLOWED_DSN_PARAMS):
        value = raw_params.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if key == "sslmode":
            sslmode = text.lower()
            if sslmode in _ALLOWED_SSLMODES:
                params[key] = sslmode
            continue
        params[key] = text

    ssl_value = raw_params.get("ssl")
    if "sslmode" not in params and ssl_value is not None:
        if isinstance(ssl_value, bool):
            params["sslmode"] = "require" if ssl_value else "disable"
        else:
            sslmode = str(ssl_value).strip().lower()
            if sslmode in _ALLOWED_SSLMODES:
                params["sslmode"] = sslmode
    return urlencode(params)


def _connect_timeout(config: dict[str, Any], default: int) -> int:
    raw_params = _extra_params(config)
    raw = raw_params.get("connect_timeout", raw_params.get("timeout"))
    if raw is None:
        return default
    try:
        parsed = int(float(raw))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _build_dsn(config: dict[str, Any]) -> str:
    user = quote_plus(str(config["username"]))
    password = quote_plus(str(config["password"]))
    host = str(config["host"])
    port = int(config["port"])
    database = quote_plus(str(config["database"]))
    base = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    query = _dsn_query(config)
    return f"{base}?{query}" if query else base


def _schema_name(config: dict[str, Any]) -> str:
    raw = config.get("schema_name") or CHATBI_DEFAULT_SCHEMA_NAME
    return str(raw).strip() or CHATBI_DEFAULT_SCHEMA_NAME


def _quote_pg_ident(name: str) -> str:
    return f'"{name.replace('"', '""')}"'


def _search_path_sql(config: dict[str, Any], *, local: bool = False) -> str:
    schema = _schema_name(config)
    prefix = "SET LOCAL" if local else "SET"
    return f"{prefix} search_path TO {_quote_pg_ident(schema)}"


def _statement_timeout_sql(timeout_seconds: float | None) -> str:
    timeout = timeout_seconds or CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS
    timeout_ms = max(int(float(timeout) * 1000), 1)
    return f"SET LOCAL statement_timeout = {timeout_ms}"


async def _set_search_path(conn: asyncpg.Connection, config: dict[str, Any]) -> None:
    await conn.execute(_search_path_sql(config))


def _mask_sql_comments_and_literals(sql: str) -> str:
    without_comments = _SQL_COMMENT_PATTERN.sub(" ", sql)
    return _SQL_LITERAL_PATTERN.sub("''", without_comments)


def _validate_readonly_sql(sql: str) -> str:
    text = sql.strip().rstrip(";")
    if not text:
        msg = "sql 不能为空"
        raise ValueError(msg)
    masked = _mask_sql_comments_and_literals(text)
    if ";" in masked:
        msg = "仅允许单条 SQL 语句"
        raise ValueError(msg)
    first_token = re.match(r"\s*([A-Za-z_]+)", masked)
    if first_token is None or first_token.group(1).lower() not in _ALLOWED_READONLY_START:
        msg = "仅允许只读 SELECT 查询"
        raise ValueError(msg)
    if _FORBIDDEN_READONLY_KEYWORDS.search(masked):
        msg = "仅允许只读 SELECT 查询"
        raise ValueError(msg)
    return text


def validate_readonly_postgres_sql(sql: str) -> str:
    """校验可保存/执行的 PostgreSQL 只读查询。"""

    return _validate_readonly_sql(sql)


def _limit_readonly_sql(sql: str, max_rows: int | None) -> str:
    if max_rows is None or max_rows <= 0:
        return sql
    return f"SELECT * FROM ({sql}) AS _chatbi_readonly_result LIMIT {max_rows + 1}"  # nosec


class PostgreSQLConnector(BaseDatasourceConnector):
    """基于 asyncpg 的默认实现。"""

    async def test_connection(self, config: dict[str, Any]) -> bool:
        dsn = _build_dsn(config)
        try:
            conn = await asyncpg.connect(dsn, timeout=_connect_timeout(config, 15))
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            await _set_search_path(conn, config)
            await conn.fetchval("SELECT 1")
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        finally:
            await conn.close()
        return True

    async def execute_readonly_sql(
        self,
        config: dict[str, Any],
        sql: str,
        *,
        max_rows: int | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        text = _validate_readonly_sql(sql)
        query = _limit_readonly_sql(text, max_rows)
        dsn = _build_dsn(config)
        timeout = timeout_seconds or CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS
        try:
            conn = await asyncpg.connect(
                dsn,
                timeout=_connect_timeout(config, 30),
                command_timeout=timeout,
            )
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            async with conn.transaction(readonly=True):
                await conn.execute(_statement_timeout_sql(timeout))
                await conn.execute(_search_path_sql(config, local=True))
                statement = await conn.prepare(query)
                rows = await statement.fetch(timeout=timeout)
                columns = [attr.name for attr in statement.get_attributes()]
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        finally:
            await conn.close()
        if not rows:
            return columns, []
        dict_rows = [dict(r) for r in rows]
        return columns, dict_rows

    async def execute_sql(self, config: dict[str, Any], sql: str) -> None:
        text = sql.strip()
        if not text:
            msg = "sql 不能为空"
            raise ValueError(msg)
        await self.execute_sql_transaction(config, [text])

    async def execute_sql_transaction(
        self,
        config: dict[str, Any],
        statements: list[str],
    ) -> None:
        cleaned = [sql.strip() for sql in statements if sql.strip()]
        if not cleaned:
            msg = "sql 不能为空"
            raise ValueError(msg)
        dsn = _build_dsn(config)
        try:
            conn = await asyncpg.connect(dsn, timeout=_connect_timeout(config, 60))
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            await _set_search_path(conn, config)
            async with conn.transaction():
                for statement in cleaned:
                    await conn.execute(statement)
        finally:
            await conn.close()

    async def execute_table_import(
        self,
        config: dict[str, Any],
        *,
        ddl_statements: list[str],
        insert_sql: str,
        rows: Iterator[tuple[object | None, ...]],
        batch_size: int,
    ) -> None:
        cleaned_ddl = [sql.strip() for sql in ddl_statements if sql.strip()]
        text = insert_sql.strip()
        if not cleaned_ddl or not text:
            msg = "sql 不能为空"
            raise ValueError(msg)
        size = max(int(batch_size), 1)
        dsn = _build_dsn(config)
        try:
            conn = await asyncpg.connect(dsn, timeout=_connect_timeout(config, 60))
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            await _set_search_path(conn, config)
            async with conn.transaction():
                for statement in cleaned_ddl:
                    await conn.execute(statement)
                batch: list[tuple[object | None, ...]] = []
                for row in rows:
                    batch.append(row)
                    if len(batch) >= size:
                        await conn.executemany(text, batch)
                        batch.clear()
                if batch:
                    await conn.executemany(text, batch)
        finally:
            await conn.close()

    async def get_structure(self, config: dict[str, Any]) -> ChatbiDbSchemaRecord:
        schema = _schema_name(config)
        database_name = str(config["database"])
        dsn = _build_dsn(config)
        try:
            conn = await asyncpg.connect(
                dsn,
                timeout=_connect_timeout(config, 60),
                command_timeout=CHATBI_STRUCTURE_LOAD_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            tables = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = $1 AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                schema,
                timeout=CHATBI_STRUCTURE_LOAD_TIMEOUT_SECONDS,
            )
            out_tables: list[ChatbiDbSchemaTableRecord] = []
            sampled_columns = 0
            for table_idx, row in enumerate(tables):
                table_name = str(row["table_name"])
                columns = await conn.fetch(
                    """
                    SELECT
                        c.column_name,
                        c.data_type,
                        c.is_nullable,
                        pgd.description AS col_description
                    FROM information_schema.columns c
                    LEFT JOIN pg_catalog.pg_statio_all_tables st
                        ON st.schemaname = c.table_schema AND st.relname = c.table_name
                    LEFT JOIN pg_catalog.pg_description pgd
                        ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
                    WHERE c.table_schema = $1 AND c.table_name = $2
                    ORDER BY c.ordinal_position
                    """,
                    schema,
                    table_name,
                    timeout=CHATBI_STRUCTURE_LOAD_TIMEOUT_SECONDS,
                )
                pk_cols = await conn.fetch(
                    """
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = $1
                      AND tc.table_name = $2
                    ORDER BY kcu.ordinal_position
                    """,
                    schema,
                    table_name,
                    timeout=CHATBI_STRUCTURE_LOAD_TIMEOUT_SECONDS,
                )
                pk_set = {str(r["column_name"]) for r in pk_cols}
                fk_rows = await conn.fetch(
                    """
                    SELECT
                        kcu.column_name,
                        ccu.table_name AS foreign_table_name,
                        ccu.column_name AS foreign_column_name,
                        tc.constraint_name
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                      AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = $1
                      AND tc.table_name = $2
                    """,
                    schema,
                    table_name,
                    timeout=CHATBI_STRUCTURE_LOAD_TIMEOUT_SECONDS,
                )
                col_list: list[ChatbiDbSchemaColumnRecord] = []
                for col in columns:
                    cname = str(col["column_name"])
                    constraints: list[str] = []
                    if cname in pk_set:
                        constraints.append("PRIMARY KEY")
                    if str(col["is_nullable"]).upper() == "NO":
                        constraints.append("NOT NULL")
                    samples: list[str] = []
                    if (
                        table_idx < CHATBI_STRUCTURE_SAMPLE_TABLE_LIMIT
                        and sampled_columns < CHATBI_STRUCTURE_SAMPLE_COLUMN_LIMIT
                    ):
                        sampled_columns += 1
                        try:
                            sample_sql = (
                                f"SELECT {_quote_pg_ident(cname)} AS v "
                                f"FROM {_quote_pg_ident(schema)}.{_quote_pg_ident(table_name)} "
                                f"WHERE {_quote_pg_ident(cname)} IS NOT NULL "
                                "LIMIT 3"  # nosec
                            )
                            srows = await conn.fetch(
                                sample_sql,
                                timeout=CHATBI_STRUCTURE_SAMPLE_TIMEOUT_SECONDS,
                            )
                            for sr in srows:
                                v = sr.get("v")
                                if v is not None:
                                    samples.append(str(v)[:200])
                        except Exception:
                            samples = []
                    col_list.append(
                        ChatbiDbSchemaColumnRecord(
                            name=cname,
                            type=str(col["data_type"]),
                            constraints=constraints,
                            comment=(str(col["col_description"]) if col["col_description"] else "")
                            or "",
                            description="",
                            samples=samples,
                        )
                    )
                fk_list = [
                    ChatbiDbSchemaForeignKeyRecord(
                        column=str(fr["column_name"]),
                        references=ChatbiDbSchemaForeignKeyRefRecord(
                            table=str(fr["foreign_table_name"]),
                            column=str(fr["foreign_column_name"]),
                        ),
                        constraint_name=str(fr["constraint_name"]),
                    )
                    for fr in fk_rows
                ]
                out_tables.append(
                    ChatbiDbSchemaTableRecord(
                        table_name=table_name,
                        columns=col_list,
                        foreign_keys=fk_list,
                    )
                )
        finally:
            await conn.close()
        return ChatbiDbSchemaRecord(
            database=database_name,
            description="",
            tables=out_tables,
        )


__all__ = ["PostgreSQLConnector", "validate_readonly_postgres_sql"]
