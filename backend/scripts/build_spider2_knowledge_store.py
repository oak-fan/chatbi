"""Build a pgvector knowledge store from Spider2 external_knowledge .md files.

Reads chatbi_local.jsonl to discover which databases have external_knowledge,
then reads the referenced .md files from resource/documents/ and builds
per-database knowledge chunks written to the same bird_dev_knowledge_chunks
table used by BIRD-DEV.

Example:
    .venv/bin/python scripts/build_spider2_knowledge_store.py

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
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
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
        "--spider2-root",
        default=os.getenv(
            "CHATBI_SPIDER2_ROOT",
            str(ROOT.parent / "Spider2" / "spider2-lite"),
        ),
        help="Path to Spider2 spider2-lite/ directory.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv(KNOWLEDGE_DATABASE_URL_ENV, DEFAULT_KNOWLEDGE_DATABASE_URL),
        help="Target PostgreSQL async SQLAlchemy URL.",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--reset", action="store_true", help="Delete existing Spider2 chunks first.")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    spider2_root = Path(args.spider2_root).expanduser().resolve()
    if not spider2_root.exists():
        raise SystemExit(f"Spider2 root path not found: {spider2_root}")

    chunks = build_chunks(spider2_root, chunk_size=max(500, int(args.chunk_size)))
    print(f"Built {len(chunks)} chunks from {spider2_root}")
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


def build_chunks(spider2_root: Path, *, chunk_size: int) -> list[KnowledgeChunk]:
    chatbi_local = spider2_root / "chatbi_local.jsonl"
    if not chatbi_local.is_file():
        raise SystemExit(f"chatbi_local.jsonl not found: {chatbi_local}")

    samples = [json.loads(line) for line in chatbi_local.read_text(encoding="utf-8").splitlines() if line.strip()]

    db_to_files: dict[str, set[str]] = defaultdict(set)
    for sample in samples:
        db_name = str(sample.get("db") or "")
        ek = sample.get("external_knowledge")
        if db_name and ek:
            db_to_files[db_name].add(str(ek))

    if not db_to_files:
        print("No samples with external_knowledge found")
        return []

    documents_dir = spider2_root / "resource" / "documents"
    if not documents_dir.is_dir():
        raise SystemExit(f"documents directory not found: {documents_dir}")

    chunks: list[KnowledgeChunk] = []
    for db_name in sorted(db_to_files.keys()):
        md_files = sorted(db_to_files[db_name])
        for md_file in md_files:
            md_path = documents_dir / md_file
            if not md_path.is_file():
                print(f"  WARN: {md_path} not found, skipping")
                continue
            text_content = md_path.read_text(encoding="utf-8")
            file_chunks = _chunk_markdown(
                db_name=db_name,
                md_file=md_file,
                source_path=f"Spider2/spider2-lite/resource/documents/{md_file}",
                text_content=text_content,
                chunk_size=chunk_size,
            )
            chunks.extend(file_chunks)
            print(f"  db={db_name}, file={md_file}, {len(file_chunks)} chunks")
    return chunks


def _chunk_markdown(
    *,
    db_name: str,
    md_file: str,
    source_path: str,
    text_content: str,
    chunk_size: int,
) -> list[KnowledgeChunk]:
    sections = _split_markdown_by_heading(text_content)
    if not sections:
        sections = [("content", text_content)]

    raw_chunks: list[str] = []
    current = ""
    for _heading, body in sections:
        body = body.strip()
        if not body:
            continue
        if len(body) > chunk_size:
            if current:
                raw_chunks.append(current.strip())
                current = ""
            sub_chunks = _split_long_text(body, chunk_size)
            raw_chunks.extend(sub_chunks)
        else:
            candidate = f"{current}\n\n{body}" if current else body
            if len(candidate) > chunk_size and current:
                raw_chunks.append(current.strip())
                current = body
            else:
                current = candidate
    if current.strip():
        raw_chunks.append(current.strip())

    chunks: list[KnowledgeChunk] = []
    for idx, content in enumerate(raw_chunks):
        table_name = _guess_table_name(content)
        digest = hashlib.sha1(
            f"{db_name}|{table_name}|{idx}|{content}".encode("utf-8")
        ).hexdigest()
        chunks.append(
            KnowledgeChunk(
                chunk_id=digest,
                db_name=db_name,
                table_name=table_name,
                source_path=source_path,
                chunk_index=idx,
                content=f"Database: {db_name}\n\n{content}",
                metadata={
                    "db_name": db_name,
                    "table_name": table_name,
                    "source_path": source_path,
                    "chunk_index": idx,
                    "source": "spider2_external_knowledge",
                    "md_file": md_file,
                },
            )
        )
    return chunks


def _split_markdown_by_heading(text: str) -> list[tuple[str, str]]:
    heading_re = re.compile(r"^(#{1,3}\s+.+)$", re.MULTILINE)
    parts: list[tuple[str, str]] = []
    positions = [(m.start(), m.end(), m.group().strip()) for m in heading_re.finditer(text)]
    if not positions:
        return [("content", text)]
    if positions[0][0] > 0:
        preamble = text[: positions[0][0]].strip()
        if preamble:
            parts.append(("preamble", preamble))
    for i, (start, end, heading) in enumerate(positions):
        next_start = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        body = text[end:next_start].strip()
        if body:
            parts.append((heading, body))
    return parts


def _split_long_text(text: str, max_len: int) -> list[str]:
    paragraphs = re.split(r"\n\n+", text)
    result: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_len and current:
            result.append(current.strip())
            current = para
        else:
            current = candidate
    if current.strip():
        result.append(current.strip())
    return result if result else [text[:max_len]]


def _guess_table_name(content: str) -> str:
    match = re.search(r"(?:table|TABLE)\s+[`\"']?(\w+)[`\"']?", content)
    if match:
        return match.group(1)
    match = re.search(r"FROM\s+[`\"']?(\w+)[`\"']?", content, re.IGNORECASE)
    if match:
        return match.group(1)
    return "external_knowledge"


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
        result = await conn.execute(
            text(
                "DELETE FROM bird_dev_knowledge_chunks WHERE metadata->>'source' = :source"
            ),
            {"source": "spider2_external_knowledge"},
        )
        print(f"Deleted {result.rowcount} existing Spider2 external_knowledge chunks")


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
