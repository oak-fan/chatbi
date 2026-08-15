"""MySQL 数据源连接器实现。"""

from __future__ import annotations

import re
from typing import Any

import pymysql
import pymysql.cursors

from ......constants.chatbi.datasource import (
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
    r"call|execute|copy|set|reset|into"
    r")\b",
    flags=re.IGNORECASE,
)
_SQL_COMMENT_PATTERN = re.compile(r"(--[^\n\r]*|/\*.*?\*/)", flags=re.DOTALL)
_SQL_LITERAL_PATTERN = re.compile(
    r"('([^']|'')*'|\"([^\"]|\"\")*\")",
    flags=re.DOTALL,
)


def _extra_params(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("extra_params")
    return dict(raw) if isinstance(raw, dict) else {}


def _connect_params(config: dict[str, Any]) -> dict[str, Any]:
    params = _extra_params(config)
    host = str(config.get("host") or params.get("host") or "127.0.0.1")
    port = int(config.get("port") or params.get("port") or 3306)
    user = str(config.get("username") or params.get("username") or "root")
    password = str(config.get("password") or params.get("password") or "")
    database = str(config.get("database") or params.get("database") or "")

    connect_timeout = int(float(params.get("connect_timeout", params.get("timeout", 15))))

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
        "charset": "utf8mb4",
        "connect_timeout": connect_timeout,
        "read_timeout": int(float(CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS)),
        "write_timeout": int(float(CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS)),
        "cursorclass": pymysql.cursors.DictCursor,
    }


def _get_connection(config: dict[str, Any]) -> pymysql.Connection:
    params = _connect_params(config)
    params["cursorclass"] = pymysql.cursors.DictCursor
    try:
        return pymysql.connect(**params)
    except Exception as exc:
        raise ConnectionTestError(str(exc)) from exc


def _row_val(row: dict, key: str) -> Any:
    """从 DictCursor 行中取值，兼容大小写。"""
    if key in row:
        return row[key]
    return row.get(key.upper()) or row.get(key.lower())


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
    return f"SELECT * FROM ({sql}) AS _chatbi_readonly_result LIMIT {max_rows + 1}"  # nosec


def _quote_mysql_ident(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


class MySQLConnector(BaseDatasourceConnector):
    """基于 PyMySQL 的 MySQL 连接器。"""

    async def test_connection(self, config: dict[str, Any]) -> bool:
        try:
            conn = _get_connection(config)
        except ConnectionTestError:
            raise
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        finally:
            conn.close()
        return True

    async def get_structure(self, config: dict[str, Any]) -> ChatbiDbSchemaRecord:
        database_name = str(config.get("database") or "")
        try:
            conn = _get_connection(config)
        except ConnectionTestError:
            raise
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """,
                    (database_name,),
                )
                tables = cur.fetchall()

                out_tables: list[ChatbiDbSchemaTableRecord] = []
                sampled_columns = 0
                for table_idx, row in enumerate(tables):
                    table_name = str(_row_val(row, "table_name"))

                    cur.execute(
                        """
                        SELECT column_name, data_type, is_nullable, column_comment
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (database_name, table_name),
                    )
                    columns = cur.fetchall()

                    cur.execute(
                        """
                        SELECT column_name
                        FROM information_schema.key_column_usage
                        WHERE table_schema = %s AND table_name = %s
                          AND constraint_name = 'PRIMARY'
                        ORDER BY ordinal_position
                        """,
                        (database_name, table_name),
                    )
                    pk_rows = cur.fetchall()
                    pk_set = {str(_row_val(r, "column_name")) for r in pk_rows}

                    cur.execute(
                        """
                        SELECT
                            kcu.column_name,
                            kcu.referenced_table_name AS foreign_table_name,
                            kcu.referenced_column_name AS foreign_column_name,
                            kcu.constraint_name
                        FROM information_schema.key_column_usage kcu
                        WHERE kcu.table_schema = %s
                          AND kcu.table_name = %s
                          AND kcu.referenced_table_name IS NOT NULL
                        """,
                        (database_name, table_name),
                    )
                    fk_rows = cur.fetchall()

                    col_list: list[ChatbiDbSchemaColumnRecord] = []
                    for col in columns:
                        cname = str(_row_val(col, "column_name"))
                        constraints: list[str] = []
                        if cname in pk_set:
                            constraints.append("PRIMARY KEY")
                        if str(_row_val(col, "is_nullable")).upper() == "NO":
                            constraints.append("NOT NULL")
                        samples: list[str] = []
                        if (
                            table_idx < CHATBI_STRUCTURE_SAMPLE_TABLE_LIMIT
                            and sampled_columns < CHATBI_STRUCTURE_SAMPLE_COLUMN_LIMIT
                        ):
                            sampled_columns += 1
                            try:
                                sample_sql = (
                                    f"SELECT {_quote_mysql_ident(cname)} AS v "
                                    f"FROM {_quote_mysql_ident(database_name)}.{_quote_mysql_ident(table_name)} "
                                    f"WHERE {_quote_mysql_ident(cname)} IS NOT NULL "
                                    "LIMIT 3"
                                )
                                cur.execute(sample_sql)
                                for sr in cur.fetchall():
                                    v = sr.get("v")
                                    if v is not None:
                                        samples.append(str(v)[:200])
                            except Exception:
                                samples = []
                        col_list.append(
                            ChatbiDbSchemaColumnRecord(
                                name=cname,
                                type=str(_row_val(col, "data_type")),
                                constraints=constraints,
                                comment=(str(col.get("column_comment") or col.get("COLUMN_COMMENT") or "")),
                                description="",
                                samples=samples,
                            )
                        )
                    fk_list = [
                        ChatbiDbSchemaForeignKeyRecord(
                            column=str(_row_val(fr, "column_name")),
                            references=ChatbiDbSchemaForeignKeyRefRecord(
                                table=str(_row_val(fr, "foreign_table_name")),
                                column=str(_row_val(fr, "foreign_column_name")),
                            ),
                            constraint_name=str(_row_val(fr, "constraint_name")),
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
            conn.close()
        return ChatbiDbSchemaRecord(
            database=database_name,
            description="",
            tables=out_tables,
        )

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
        try:
            conn = _get_connection(config)
        except ConnectionTestError:
            raise
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
                columns = [desc[0] for cur_desc in cur.description for desc in [cur.description]] if cur.description else []
                if cur.description:
                    columns = [d[0] for d in cur.description]
        finally:
            conn.close()
        if not rows:
            return columns if columns else [], []
        return columns, [dict(r) for r in rows]

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
        try:
            conn = _get_connection(config)
        except ConnectionTestError:
            raise
        except Exception as exc:
            raise ConnectionTestError(str(exc)) from exc
        try:
            with conn.cursor() as cur:
                for statement in cleaned:
                    cur.execute(statement)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


__all__ = ["MySQLConnector"]
