#!/usr/bin/env python3
"""Import BIRD train examples into ChatBI global Q-SQL pool (cogmait-chatbi)."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = PROJECT_ROOT.parent / "cogmait-backend-v2" / "shared"
TRAIN_DEFAULT = PROJECT_ROOT.parent / "train_bird.json"
sys.path[:0] = [str(PROJECT_ROOT), str(SHARED_ROOT)]

SOURCE_DATASET = "BIRD"


def _load_env() -> None:
    for name in (".env", ".env.local"):
        path = PROJECT_ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _sample_sql(item: dict[str, Any]) -> str:
    for key in ("SQL", "sql", "query"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _sample_id(index: int, item: dict[str, Any]) -> str:
    db_id = str(item.get("db_id") or "").strip()
    question = str(item.get("question") or "").strip()
    sql = _sample_sql(item)
    digest = hashlib.sha1(f"{db_id}\0{question}\0{sql}".encode()).hexdigest()[:16]
    return f"train:{index}:{digest}"


async def _run(path: Path, *, limit: int | None, batch_size: int) -> None:
    _load_env()
    from app.constants.chatbi.datasource import CHATBI_VECTOR_DIMENSIONS
    from app.core.config import get_settings
    from app.core.database import get_default_database
    from app.domain.system.chatbi import (
        QSQL_GLOBAL_DATASOURCE_ID,
        QSQL_SCOPE_GLOBAL,
        ChatbiQsqlCreateInput,
    )
    from app.domain.system.llm import EmbeddingRequest
    from app.repositories.system.chatbi import ChatbiQsqlRepository
    from app.services.system.chatbi.query.qsql_retrieval import (
        build_sql_skeleton_from_sql,
        build_sql_skeleton_from_tokens,
    )
    from app.services.system.chatbi.vector import (
        ChatbiVectorStore,
        build_chatbi_vector_settings,
        initialize_chatbi_vector_backend,
    )
    from app.services.system.llm_service import get_default_llm_service
    from cogmait_shared.db import UnitOfWork

    get_settings.cache_clear()
    settings = get_settings()
    initialize_chatbi_vector_backend(build_chatbi_vector_settings(settings))
    samples = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(samples, list):
        raise SystemExit("Input must be a JSON array")
    if limit is not None:
        samples = samples[:limit]

    user_id = int(os.environ.get("DEFAULT_USER_ID", "1"))
    database = get_default_database()
    database.initialize()
    llm = get_default_llm_service()
    imported = 0
    skipped = 0

    async with database.get_session() as session:
        repo = ChatbiQsqlRepository(session)
        uow = UnitOfWork(session)
        vector_store = ChatbiVectorStore(
            session=session,
            store_settings=build_chatbi_vector_settings(settings),
        )
        for start in range(0, len(samples), batch_size):
            batch = samples[start : start + batch_size]
            payloads: list[ChatbiQsqlCreateInput] = []
            for offset, item in enumerate(batch):
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question") or "").strip()
                sql_body = _sample_sql(item)
                db_id = str(item.get("db_id") or "").strip()
                if not question or not sql_body or not db_id:
                    continue
                tokens = item.get("query_toks_no_value")
                if isinstance(tokens, list) and tokens:
                    skeleton = build_sql_skeleton_from_tokens(tokens)
                else:
                    skeleton = build_sql_skeleton_from_sql(sql_body)
                payloads.append(
                    ChatbiQsqlCreateInput(
                        user_id=user_id,
                        datasource_id=QSQL_GLOBAL_DATASOURCE_ID,
                        question=question,
                        sql_body=sql_body,
                        scope=QSQL_SCOPE_GLOBAL,
                        source_dataset=SOURCE_DATASET,
                        source_db_id=db_id,
                        source_sample_id=_sample_id(start + offset, item),
                        sql_skeleton=skeleton,
                    )
                )
            existing = await repo.list_existing_global_source_sample_ids(
                source_dataset=SOURCE_DATASET,
                source_sample_ids=[
                    str(item.source_sample_id)
                    for item in payloads
                    if item.source_sample_id is not None
                ],
            )
            pending = [
                item
                for item in payloads
                if item.source_sample_id is not None and item.source_sample_id not in existing
            ]
            skipped += len(payloads) - len(pending)
            if not pending:
                continue
            emb = await llm.aembedding(
                EmbeddingRequest(input_texts=[item.question for item in pending])
            )
            for payload, vector in zip(pending, emb.embeddings, strict=True):
                if len(vector) != CHATBI_VECTOR_DIMENSIONS:
                    raise RuntimeError("Embedding dimension mismatch")
                qsql_id = await repo.create(payload)
                await vector_store.upsert_qsql_vector(
                    qsql_id=qsql_id,
                    datasource_id=QSQL_GLOBAL_DATASOURCE_ID,
                    embedding=vector,
                    user_id=user_id,
                )
                imported += 1
            await uow.commit()
    await database.dispose()
    print(json.dumps({"imported": imported, "skipped": skipped, "source": str(path)}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import train_bird.json into global Q-SQL pool")
    parser.add_argument("--path", type=Path, default=TRAIN_DEFAULT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    asyncio.run(_run(args.path, limit=args.limit, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
