#!/usr/bin/env python3
"""将 MySQL dump 文件导入远程 MySQL 服务器。"""
import re
import sys
import pymysql

HOST = "47.94.248.19"
PORT = 18003
USER = "root"
PASSWORD = "123456"

DUMPS = {
    "beaver_neutron": "/home/fan/LAB_ing/chatbi/BEAVER/beaver-table/beaver_db/neutron.sql",
    "beaver_dw": "/home/fan/LAB_ing/chatbi/BEAVER/beaver-table/beaver_db/dw.sql",
    "beaver_nova": "/home/fan/LAB_ing/chatbi/BEAVER/beaver-table/beaver_db/nova.sql",
}


def clean_statement(stmt: str) -> str | None:
    """清洗单条 MySQL 语句，返回可执行 SQL 或 None（表示应跳过）。"""
    s = stmt.strip()
    if not s:
        return None

    lower = s.lower()

    # 跳过 LOCK / UNLOCK
    if lower.startswith("lock tables") or lower.startswith("unlock tables"):
        return None

    # 跳过 SET 语句（character_set 等）
    if lower.startswith("set ") and (
        "character_set" in lower
        or "collation" in lower
        or "saved_cs" in lower
        or "sql_mode" in lower
    ):
        return None

    # 清理 MySQL 条件注释 /*!00000 ... */
    cleaned = re.sub(r"/\*!\d+\s*", "", s)
    cleaned = cleaned.replace("*/", "")

    # 跳过纯注释
    if cleaned.strip().startswith("--") or cleaned.strip().startswith("#"):
        return None

    return cleaned.strip().rstrip(";").strip() or None


def split_sql(content: str) -> list[str]:
    """按分号分割 SQL，正确处理字符串内的分号。"""
    statements = []
    current = []
    in_string = False
    escape_next = False
    quote_char = None

    i = 0
    while i < len(content):
        c = content[i]
        if escape_next:
            current.append(c)
            escape_next = False
            i += 1
            continue
        if c == "\\" and in_string:
            current.append(c)
            escape_next = True
            i += 1
            continue
        if c in ("'", '"') and not in_string:
            in_string = True
            quote_char = c
            current.append(c)
            i += 1
            continue
        if c == quote_char and in_string:
            if i + 1 < len(content) and content[i + 1] == quote_char:
                current.append(c)
                current.append(c)
                i += 2
                continue
            in_string = False
            quote_char = None
            current.append(c)
            i += 1
            continue
        if not in_string and c == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue
        current.append(c)
        i += 1

    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


def import_dump(database: str, sql_file: str):
    print(f"\n{'='*60}")
    print(f"Importing {sql_file} → {database}")
    print(f"{'='*60}")

    # 读取文件
    with open(sql_file, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    print(f"  File size: {len(content):,} bytes")

    # 分割
    raw_stmts = split_sql(content)
    print(f"  Raw statements: {len(raw_stmts)}")

    # 清洗
    clean_stmts = []
    for s in raw_stmts:
        c = clean_statement(s)
        if c:
            clean_stmts.append(c)
    print(f"  After cleaning: {len(clean_stmts)}")

    # 连接
    conn = pymysql.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD,
        database=database, charset="utf8mb4",
        max_allowed_packet=67108864,
        read_timeout=300, write_timeout=300,
    )
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute("SET UNIQUE_CHECKS=0")
    cur.execute("SET autocommit=0")

    executed = 0
    errors = 0
    batch = 0

    for idx, stmt in enumerate(clean_stmts):
        try:
            cur.execute(stmt)
            executed += 1
        except Exception as e:
            err = str(e)
            # 忽略常见无害错误
            if any(kw in err for kw in ["Duplicate", "already exists", "1050", "1061", "1062"]):
                executed += 1
            else:
                errors += 1
                if errors <= 5:
                    print(f"  ERR #{errors} stmt {idx}: {err[:150]}")
                elif errors == 6:
                    print(f"  ... suppressing further errors ...")

        batch += 1
        if batch % 1000 == 0:
            conn.commit()
            print(f"  Progress: {idx+1}/{len(clean_stmts)} (ok={executed}, err={errors})")

    conn.commit()
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    cur.execute("SET UNIQUE_CHECKS=1")
    cur.execute("SET autocommit=1")

    # 统计
    cur.execute("SHOW TABLES")
    tables = cur.fetchall()
    total_rows = 0
    for (t,) in tables:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        total_rows += cur.fetchone()[0]

    print(f"  Result: {len(tables)} tables, {total_rows:,} rows, {executed} executed, {errors} errors")
    cur.close()
    conn.close()
    return len(tables), total_rows, errors


if __name__ == "__main__":
    total_tables = 0
    total_rows = 0
    total_errors = 0
    for db, path in DUMPS.items():
        # 创建数据库
        conn = pymysql.connect(host=HOST, port=PORT, user=USER, password=PASSWORD)
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
        cur.execute(f"CREATE DATABASE `{db}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cur.close()
        conn.close()

        tables, rows, errors = import_dump(db, path)
        total_tables += tables
        total_rows += rows
        total_errors += errors

    print(f"\n{'='*60}")
    print(f"ALL DONE: {total_tables} tables, {total_rows:,} rows, {total_errors} errors")
