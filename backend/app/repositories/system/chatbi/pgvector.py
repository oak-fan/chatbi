"""ChatBI pgvector 字面量工具（供向量仓储 raw SQL 使用）。"""

from __future__ import annotations


def to_pgvector_literal(embedding: list[float]) -> str:
    """与 knowledge PostgresVectorStore 一致，供 asyncpg CAST AS vector 使用。"""
    return "[" + ",".join(f"{value:.12g}" for value in embedding) + "]"


__all__ = ["to_pgvector_literal"]
