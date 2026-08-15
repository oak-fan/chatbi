"""Build a pgvector knowledge store from BIRD-DEV database_description files.

Example:
    .venv/bin/python scripts/build_bird_dev_knowledge_store.py \
        --bird-dev-root ../BIRD-DEV/dev_databases

The target database defaults to:
postgresql+asyncpg://postgres:123456@47.94.248.19:18004/postgres
Override it with --database-url or CHATBI_MULTI_AGENT_KNOWLEDGE_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import os
import sys
from dataclasses import dataclass
from io import StringIO
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


@dataclass(slots=True)
class KnowledgeChunk:
    chunk_id: str
    db_name: str
    table_name: str
    source_path: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bird-dev-root",
        default=os.getenv("CHATBI_BIRD_DEV_DATABASES_ROOT", "../BIRD-DEV/dev_databases"),
        help="Path to BIRD-DEV/dev_databases.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv(KNOWLEDGE_DATABASE_URL_ENV, DEFAULT_KNOWLEDGE_DATABASE_URL),
        help="Target PostgreSQL async SQLAlchemy URL.",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--reset", action="store_true", help="Delete existing chunks first.")
    parser.add_argument(
        "--strict-encoding",
        action="store_true",
        help="Fail if a CSV cannot be decoded with the known encoding fallbacks.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    bird_root = Path(args.bird_dev_root).expanduser().resolve()
    if not bird_root.exists():
        raise SystemExit(f"BIRD dev_databases path not found: {bird_root}")

    chunks = build_chunks(
        bird_root,
        chunk_size=max(500, int(args.chunk_size)),
        strict_encoding=bool(args.strict_encoding),
    )
    print(f"Loaded {len(chunks)} chunks from {bird_root}")
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
    db_count = len({chunk.db_name for chunk in chunks})
    print(f"Done. Upserted {len(chunks)} chunks for {db_count} databases.")


def build_chunks(root: Path, *, chunk_size: int, strict_encoding: bool = False) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for description_dir in sorted(root.glob("*/database_description")):
        if not description_dir.is_dir():
            continue
        db_name = description_dir.parent.name
        for csv_path in sorted(description_dir.glob("*.csv")):
            table_name = csv_path.stem
            row_texts = _read_description_rows(csv_path, strict_encoding=strict_encoding)
            chunks.extend(
                _chunk_table_texts(
                    db_name=db_name,
                    table_name=table_name,
                    source_path=str(csv_path.relative_to(root)),
                    row_texts=row_texts,
                    chunk_size=chunk_size,
                )
            )
    return chunks


def _read_description_rows(csv_path: Path, *, strict_encoding: bool = False) -> list[str]:
    rows: list[str] = []
    csv_text, encoding = _decode_csv_text(csv_path, strict_encoding=strict_encoding)
    if encoding != "utf-8-sig":
        print(f"Decoded {csv_path} with {encoding}")
    reader = csv.DictReader(StringIO(csv_text))
    for raw in reader:
        cleaned = {str(k or "").strip(): str(v or "").strip() for k, v in raw.items()}
        original = cleaned.get("original_column_name", "")
        column_name = cleaned.get("column_name", "")
        column_description = cleaned.get("column_description", "")
        data_format = cleaned.get("data_format", "")
        value_description = cleaned.get("value_description", "")
        parts = [
            f"original_column_name: {original}" if original else "",
            f"column_name: {column_name}" if column_name else "",
            f"column_description: {column_description}" if column_description else "",
            f"data_format: {data_format}" if data_format else "",
            f"value_description: {value_description}" if value_description else "",
        ]
        text_row = "\n".join(part for part in parts if part)
        if text_row:
            rows.append(text_row)
    return rows


def _decode_csv_text(csv_path: Path, *, strict_encoding: bool) -> tuple[str, str]:
    data = csv_path.read_bytes()
    encodings = ("utf-8-sig", "utf-8", "cp1252", "gb18030", "latin-1")
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if strict_encoding and last_error is not None:
        raise last_error
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


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
            "Columns:",
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
        await conn.execute(text("TRUNCATE TABLE bird_dev_knowledge_chunks"))


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
                    "metadata": _json_dumps(chunk.metadata),
                    "embedding": to_pgvector_literal(embedding),
                }
            )
        async with engine.begin() as conn:
            await conn.execute(stmt, rows)
        print(f"Upserted {min(start + batch_size, len(chunks))}/{len(chunks)}")


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
