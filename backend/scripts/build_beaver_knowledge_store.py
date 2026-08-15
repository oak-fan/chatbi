"""Build a pgvector knowledge store from BEAVER domain_knowledge and column_mapping.

Reads each domain's example.json, extracts column_mapping, domain_knowledge,
and join_keys, then builds per-table knowledge chunks written to the same
bird_dev_knowledge_chunks table used by BIRD-DEV.

Example:
    .venv/bin/python scripts/build_beaver_knowledge_store.py

The target database defaults to:
postgresql+asyncpg://postgres:123456@47.94.248.19:18004/postgres
Override it with --database-url or CHATBI_MULTI_AGENT_KNOWLEDGE_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.system.llm import EmbeddingRequest  # noqa: E402
from app.repositories.system.chatbi.pgvector import to_pgvector_literal  # noqa: E402
from app.services.system.chatbi.multi_agent.tools import (  # noqa: E402
    DEFAULT_KNOWLEDGE_DATABASE_URL,
    KNOWLEDGE_DATABASE_URL_ENV,
)
from app.services.system.llm_service import LLMService  # noqa: E402

DOMAIN_DB_MAP = {
    "dw": "dw",
    "dw_real": "dw",
    "neutron": "neutron",
    "nova": "nova",
}


@dataclass(slots=True)
class KnowledgeChunk:
    chunk_id: str
    db_name: str
    table_name: str
    source_path: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class _TableKnowledge:
    column_mapping: dict[str, list[str]] = field(default_factory=dict)
    domain_knowledge: list[str] = field(default_factory=list)
    join_keys: list[list[str]] = field(default_factory=list)
    sample_questions: list[str] = field(default_factory=list)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--beaver-root",
        default=os.getenv("CHATBI_BEAVER_ROOT", str(ROOT.parent / "BEAVER")),
        help="Path to BEAVER root (contains beaver/data/).",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv(KNOWLEDGE_DATABASE_URL_ENV, DEFAULT_KNOWLEDGE_DATABASE_URL),
        help="Target PostgreSQL async SQLAlchemy URL.",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--reset", action="store_true", help="Delete existing BEAVER chunks first.")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    beaver_root = Path(args.beaver_root).expanduser().resolve()
    if not beaver_root.exists():
        raise SystemExit(f"BEAVER root path not found: {beaver_root}")

    chunks = build_chunks(beaver_root, chunk_size=max(500, int(args.chunk_size)))
    print(f"Built {len(chunks)} chunks from {beaver_root}")
    if not chunks:
        return

    engine = create_async_engine(args.database_url)
    llm = LLMService()
    try:
        await ensure_schema(engine)
        if args.reset:
            await reset_chunks(engine)
        await upsert_chunks(
            engine=engine,
            llm=llm,
            chunks=chunks,
            batch_size=max(1, int(args.batch_size)),
        )
    finally:
        await engine.dispose()
    db_names = sorted({chunk.db_name for chunk in chunks})
    print(f"Done. Upserted {len(chunks)} chunks for {db_names}.")


def build_chunks(beaver_root: Path, *, chunk_size: int) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for domain in ["dw", "dw_real", "neutron", "nova"]:
        data_path = beaver_root / "beaver" / "data" / domain / "example.json"
        if not data_path.is_file():
            print(f"  WARN: {data_path} not found, skipping")
            continue
        data = json.loads(data_path.read_text(encoding="utf-8"))
        db_name = DOMAIN_DB_MAP[domain]
        table_knowledge = _collect_table_knowledge(data)
        domain_chunks = _build_domain_chunks(
            db_name=db_name,
            source_path=f"BEAVER/beaver/data/{domain}/example.json",
            table_knowledge=table_knowledge,
            chunk_size=chunk_size,
        )
        chunks.extend(domain_chunks)
        print(f"  {domain} -> db_name={db_name}, {len(domain_chunks)} chunks")
    return chunks


def _collect_table_knowledge(data: dict[str, Any]) -> dict[str, _TableKnowledge]:
    result: dict[str, _TableKnowledge] = {}

    tables = data.get("tables") or []
    for t in tables:
        result.setdefault(t, _TableKnowledge())

    column_mapping = data.get("column_mapping") or {}
    if isinstance(column_mapping, str):
        column_mapping = json.loads(column_mapping)
    for _nl_phrase, col_refs in column_mapping.items():
        if not isinstance(col_refs, list):
            continue
        for col_ref in col_refs:
            table_name = col_ref.split(".")[0] if "." in col_ref else ""
            if table_name:
                result.setdefault(table_name, _TableKnowledge())
                result[table_name].column_mapping.setdefault(_nl_phrase, []).append(col_ref)

    domain_knowledge = data.get("domain_knowledge") or []
    if isinstance(domain_knowledge, str):
        domain_knowledge = json.loads(domain_knowledge)
    for entry in domain_knowledge:
        if not isinstance(entry, str):
            continue
        _assign_domain_knowledge_to_tables(entry, result)

    join_keys = data.get("join_keys") or []
    if isinstance(join_keys, str):
        join_keys = json.loads(join_keys)
    for pair in join_keys:
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        for col_ref in pair:
            table_name = col_ref.split(".")[0] if "." in col_ref else ""
            if table_name:
                result.setdefault(table_name, _TableKnowledge())
                if pair not in result[table_name].join_keys:
                    result[table_name].join_keys.append(pair)

    question = data.get("question") or ""
    if question and tables:
        for t in tables:
            result.setdefault(t, _TableKnowledge())
            if len(result[t].sample_questions) < 3:
                result[t].sample_questions.append(question)

    return result


def _assign_domain_knowledge_to_tables(
    entry: str,
    table_knowledge: dict[str, _TableKnowledge],
) -> None:
    assigned = False
    for table_name in table_knowledge:
        if table_name in entry.upper():
            table_knowledge[table_name].domain_knowledge.append(entry)
            assigned = True
    if not assigned:
        for tk in table_knowledge.values():
            if not tk.domain_knowledge or entry not in tk.domain_knowledge:
                tk.domain_knowledge.append(entry)


def _build_domain_chunks(
    *,
    db_name: str,
    source_path: str,
    table_knowledge: dict[str, _TableKnowledge],
    chunk_size: int,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for table_name in sorted(table_knowledge.keys()):
        tk = table_knowledge[table_name]
        row_texts = _format_table_knowledge(table_name, tk)
        chunks.extend(
            _chunk_table_texts(
                db_name=db_name,
                table_name=table_name,
                source_path=source_path,
                row_texts=row_texts,
                chunk_size=chunk_size,
            )
        )
    return chunks


def _format_table_knowledge(table_name: str, tk: _TableKnowledge) -> list[str]:
    rows: list[str] = []
    if tk.column_mapping:
        lines = [f"  NL phrase \"{phrase}\" -> {', '.join(refs)}" for phrase, refs in tk.column_mapping.items()]
        rows.append("Column Mapping:\n" + "\n".join(lines))
    if tk.domain_knowledge:
        rows.append("Domain Knowledge:\n" + "\n".join(f"  {e}" for e in tk.domain_knowledge))
    if tk.join_keys:
        lines = [f"  {pair[0]} <-> {pair[1]}" for pair in tk.join_keys]
        rows.append("Join Keys:\n" + "\n".join(lines))
    if tk.sample_questions:
        rows.append("Example Questions:\n" + "\n".join(f"  {q}" for q in tk.sample_questions))
    return rows


def _chunk_table_texts(
    *,
    db_name: str,
    table_name: str,
    source_path: str,
    row_texts: list[str],
    chunk_size: int,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    current: list[str] = []
    current_len = 0
    chunk_index = 0
    for row_text in row_texts:
        addition_len = len(row_text) + 2
        if current and current_len + addition_len > chunk_size:
            chunks.append(
                _make_chunk(
                    db_name=db_name,
                    table_name=table_name,
                    source_path=source_path,
                    chunk_index=chunk_index,
                    parts=current,
                )
            )
            chunk_index += 1
            current = []
            current_len = 0
        current.append(row_text)
        current_len += addition_len
    if current:
        chunks.append(
            _make_chunk(
                db_name=db_name,
                table_name=table_name,
                source_path=source_path,
                chunk_index=chunk_index,
                parts=current,
            )
        )
    return chunks


def _make_chunk(
    *,
    db_name: str,
    table_name: str,
    source_path: str,
    chunk_index: int,
    parts: list[str],
) -> KnowledgeChunk:
    content = "\n\n".join(
        [
            f"Database: {db_name}",
            f"Table: {table_name}",
            *parts,
        ]
    )
    digest = hashlib.sha1(
        f"{db_name}|{table_name}|{chunk_index}|{content}".encode("utf-8")
    ).hexdigest()
    return KnowledgeChunk(
        chunk_id=digest,
        db_name=db_name,
        table_name=table_name,
        source_path=source_path,
        chunk_index=chunk_index,
        content=content,
        metadata={
            "db_name": db_name,
            "table_name": table_name,
            "source_path": source_path,
            "chunk_index": chunk_index,
            "source": "beaver",
        },
    )


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS bird_dev_knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    db_name TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    embedding vector NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_bird_dev_knowledge_chunks_db
                ON bird_dev_knowledge_chunks (db_name)
                """
            )
        )


async def reset_chunks(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM bird_dev_knowledge_chunks WHERE db_name IN ('dw', 'neutron', 'nova')"
            )
        )
        print("Deleted existing BEAVER chunks (db_name IN (dw, neutron, nova))")


async def upsert_chunks(
    *,
    engine: AsyncEngine,
    llm: LLMService,
    chunks: list[KnowledgeChunk],
    batch_size: int,
) -> None:
    stmt = text(
        """
        INSERT INTO bird_dev_knowledge_chunks (
            chunk_id,
            db_name,
            table_name,
            source_path,
            chunk_index,
            content,
            metadata,
            embedding
        ) VALUES (
            :chunk_id,
            :db_name,
            :table_name,
            :source_path,
            :chunk_index,
            :content,
            CAST(:metadata AS jsonb),
            CAST(:embedding AS vector)
        )
        ON CONFLICT (chunk_id) DO UPDATE
        SET
            db_name = EXCLUDED.db_name,
            table_name = EXCLUDED.table_name,
            source_path = EXCLUDED.source_path,
            chunk_index = EXCLUDED.chunk_index,
            content = EXCLUDED.content,
            metadata = EXCLUDED.metadata,
            embedding = EXCLUDED.embedding,
            updated_at = NOW()
        """
    )
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        embedding_resp = await llm.aembedding(
            EmbeddingRequest(input_texts=[chunk.content for chunk in batch])
        )
        rows = []
        for chunk, embedding in zip(batch, embedding_resp.embeddings, strict=True):
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "db_name": chunk.db_name,
                    "table_name": chunk.table_name,
                    "source_path": chunk.source_path,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
                    "embedding": to_pgvector_literal(embedding),
                }
            )
        async with engine.begin() as conn:
            await conn.execute(stmt, rows)
        print(f"Upserted {min(start + batch_size, len(chunks))}/{len(chunks)}")


if __name__ == "__main__":
    asyncio.run(main())
