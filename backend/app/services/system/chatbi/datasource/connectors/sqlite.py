"""SQLite 数据源连接器实现。"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any

from ......constants.chatbi.datasource import CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS
from ......core.config import get_settings
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
    r"insert|update|delete|replace|drop|alter|create|truncate|attach|detach|"
    r"pragma|vacuum|analyze|reindex|begin|commit|rollback"
    r")\b",
    flags=re.IGNORECASE,
)
_SQL_COMMENT_PATTERN = re.compile(r"(--[^\n\r]*|/\*.*?\*/)", flags=re.DOTALL)
_SQL_LITERAL_PATTERN = re.compile(r"('([^']|'')*'|\"([^\"]|\"\")*\")", flags=re.DOTALL)


def _benchmark_root() -> Path:
    settings = get_settings()
    root = settings.chatbi_benchmark_root or settings.chatbi_bird_minidev_root
    if root is None:
        msg = "未配置 CHATBI_BENCHMARK_ROOT 或 CHATBI_BIRD_MINIDEV_ROOT"
        raise ConnectionTestError(msg)
    return Path(root)


def resolve_sqlite_db_path(db_file: str, root: Path | None = None) -> Path:
    """解析 SQLite 相对路径，并确保结果位于挂载根目录内。"""

    base = (root or _benchmark_root()).resolve()
    relative = str(db_file or "").strip().replace("\\", "/")
    if not relative:
        msg = "SQLite 数据库文件路径不能为空"
        raise ConnectionTestError(msg)
    if relative.startswith("/") or ":" in relative:
        msg = "SQLite 数据库文件必须使用挂载目录内相对路径"
        raise ConnectionTestError(msg)
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        msg = "SQLite 数据库文件超出挂载目录"
        raise ConnectionTestError(msg) from exc
    if not target.is_file() or target.suffix.lower() != ".sqlite":
        msg = "SQLite 数据库文件不存在或类型不正确"
        raise ConnectionTestError(msg)
    return target


def _db_path(config: dict[str, Any]) -> Path:
    params = config.get("extra_params")
    data = params if isinstance(params, dict) else {}
    return resolve_sqlite_db_path(str(data.get("db_file") or ""))


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


def _limit_readonly_sql(sql: str, max_rows: int | None) -> str:
    if max_rows is None or max_rows <= 0:
        return sql
    return f"SELECT * FROM ({sql}) AS _chatbi_readonly_result LIMIT {max_rows + 1}"  # nosec B608


def _quote_ident(name: str) -> str:
    return f'"{name.replace('"', '""')}"'


def _connect_readonly(path: Path, timeout_seconds: float | None = None) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=float(timeout_seconds or CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS),
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _execute_readonly_sync(
    *,
    path: Path,
    sql: str,
    max_rows: int | None,
    timeout_seconds: float | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    query = _limit_readonly_sql(_validate_readonly_sql(sql), max_rows)
    conn = _connect_readonly(path, timeout_seconds)
    try:
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        columns = [str(item[0]) for item in (cursor.description or [])]
        return columns, [dict(row) for row in rows]
    finally:
        conn.close()


def _get_structure_sync(path: Path) -> ChatbiDbSchemaRecord:
    conn = _connect_readonly(path)
    try:
        table_rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        tables: list[ChatbiDbSchemaTableRecord] = []
        for table_row in table_rows:
            table_name = str(table_row["name"])
            columns = _load_columns(conn, table_name)
            foreign_keys = _load_foreign_keys(conn, table_name)
            if columns:
                tables.append(
                    ChatbiDbSchemaTableRecord(
                        table_name=table_name,
                        columns=columns,
                        foreign_keys=foreign_keys,
                    )
                )
    finally:
        conn.close()
    if not tables:
        msg = "SQLite 数据库未发现可用表"
        raise ConnectionTestError(msg)
    return ChatbiDbSchemaRecord(database=path.stem, description="", tables=tables)


def _load_columns(conn: sqlite3.Connection, table_name: str) -> list[ChatbiDbSchemaColumnRecord]:
    rows = conn.execute(f"PRAGMA table_info({_quote_ident(table_name)})").fetchall()  # nosec B608
    out: list[ChatbiDbSchemaColumnRecord] = []
    for row in rows:
        name = str(row["name"])
        constraints: list[str] = []
        if int(row["pk"] or 0) > 0:
            constraints.append("PRIMARY KEY")
        if int(row["notnull"] or 0) > 0:
            constraints.append("NOT NULL")
        out.append(
            ChatbiDbSchemaColumnRecord(
                name=name,
                type=str(row["type"] or "TEXT"),
                constraints=constraints,
                samples=_load_samples(conn, table_name, name),
            )
        )
    return out


def _load_samples(conn: sqlite3.Connection, table_name: str, column_name: str) -> list[str]:
    try:
        sample_sql = (
            f"SELECT {_quote_ident(column_name)} AS v "
            f"FROM {_quote_ident(table_name)} "
            f"WHERE {_quote_ident(column_name)} IS NOT NULL "
            "LIMIT 3"  # nosec B608
        )
        rows = conn.execute(sample_sql).fetchall()
    except sqlite3.Error:
        return []
    return [str(row["v"])[:200] for row in rows if row["v"] is not None]


def _load_foreign_keys(
    conn: sqlite3.Connection,
    table_name: str,
) -> list[ChatbiDbSchemaForeignKeyRecord]:
    rows = conn.execute(
        f"PRAGMA foreign_key_list({_quote_ident(table_name)})"
    ).fetchall()  # nosec B608
    return [
        ChatbiDbSchemaForeignKeyRecord(
            column=str(row["from"]),
            references=ChatbiDbSchemaForeignKeyRefRecord(
                table=str(row["table"]),
                column=str(row["to"]),
            ),
            constraint_name=f"fk_{table_name}_{row['id']}_{row['seq']}",
        )
        for row in rows
    ]


class SQLiteConnector(BaseDatasourceConnector):
    """基于 Python sqlite3 的只读连接器。"""

    async def test_connection(self, config: dict[str, Any]) -> bool:
        path = _db_path(config)
        try:
            await asyncio.to_thread(
                _execute_readonly_sync,
                path=path,
                sql="SELECT 1",
                max_rows=1,
                timeout_seconds=5,
            )
        except (sqlite3.Error, ValueError, ConnectionTestError) as exc:
            raise ConnectionTestError(str(exc)) from exc
        return True

    async def get_structure(self, config: dict[str, Any]) -> ChatbiDbSchemaRecord:
        path = _db_path(config)
        try:
            return await asyncio.to_thread(_get_structure_sync, path)
        except (sqlite3.Error, ValueError, ConnectionTestError) as exc:
            raise ConnectionTestError(str(exc)) from exc

    async def execute_readonly_sql(
        self,
        config: dict[str, Any],
        sql: str,
        *,
        max_rows: int | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        path = _db_path(config)
        try:
            return await asyncio.to_thread(
                _execute_readonly_sync,
                path=path,
                sql=sql,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )
        except (sqlite3.Error, ValueError, ConnectionTestError) as exc:
            raise ConnectionTestError(str(exc)) from exc

    async def execute_sql(self, config: dict[str, Any], sql: str) -> None:
        raise ValueError("SQLite 数据源不支持写入 SQL")

    async def execute_sql_transaction(
        self,
        config: dict[str, Any],
        statements: list[str],
    ) -> None:
        raise ValueError("SQLite 数据源不支持写入 SQL")


__all__ = ["SQLiteConnector", "resolve_sqlite_db_path"]
