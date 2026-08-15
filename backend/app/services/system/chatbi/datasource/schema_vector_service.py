"""ChatBI db_schema 列语义向量写入。"""

from __future__ import annotations

from typing import Any

from .....constants.chatbi.datasource import CHATBI_VECTOR_DIMENSIONS
from .....domain.system.llm import EmbeddingRequest
from ...llm_service import LLMService
from ..datasource_errors import ChatbiDatasourceServiceError
from ..vector import ChatbiSchemaVectorRow, ChatbiVectorStore, build_chatbi_vector_settings

TABLE_VECTOR_COLUMN = "__table__"


class ChatbiSchemaVectorService:
    """按最新 db_schema 重建列向量。"""

    def __init__(
        self,
        *,
        vector_store: ChatbiVectorStore,
        llm_service: LLMService,
    ) -> None:
        self._vector_store = vector_store
        self._llm = llm_service

    async def rebuild_vectors_for_schema(
        self,
        *,
        datasource_id: int,
        db_schema: dict[str, Any],
        user_id: int | None,
    ) -> None:
        """软删旧向量后，按表列描述批量嵌入并写入当前向量后端。"""
        texts: list[str] = []
        meta: list[tuple[str, str]] = []
        tables = db_schema.get("tables") or []
        for table in tables:
            tname = str(table.get("table_name", ""))
            table_text = _build_table_vector_text(table)
            if table_text:
                texts.append(table_text)
                meta.append((tname, TABLE_VECTOR_COLUMN))
            for col in table.get("columns") or []:
                cname = str(col.get("name", ""))
                embed_text = _build_schema_vector_text(table, col)
                texts.append(embed_text)
                meta.append((tname, cname))
        if not texts:
            await self._vector_store.rebuild_schema_vectors(
                datasource_id=datasource_id,
                rows=[],
                user_id=user_id,
            )
            return
        emb = await self._llm.aembedding(EmbeddingRequest(input_texts=texts))
        vectors = emb.embeddings
        if len(vectors) != len(meta):
            msg = "嵌入向量数量与列数不一致"
            raise ChatbiDatasourceServiceError.system_error(msg)
        expected_dim = CHATBI_VECTOR_DIMENSIONS
        if vectors and len(vectors[0]) != expected_dim:
            raise ChatbiDatasourceServiceError.bad_request(
                "向量模型维度不匹配，"
                f"期望 {expected_dim}，实际 {len(vectors[0])}，"
                "请更换模型或通过迁移调整 ChatBI 向量维度",
            )
        rows = [
            ChatbiSchemaVectorRow(
                datasource_id=datasource_id,
                table_name=tname,
                column_name=cname,
                embedding=vec,
            )
            for (tname, cname), vec in zip(meta, vectors, strict=True)
        ]
        await self._vector_store.rebuild_schema_vectors(
            datasource_id=datasource_id,
            rows=rows,
            user_id=user_id,
        )

    async def clear_vectors_for_datasource(
        self,
        *,
        datasource_id: int,
        user_id: int | None,
    ) -> None:
        """逻辑删除数据源时清理其 schema 向量。"""
        await self._vector_store.rebuild_schema_vectors(
            datasource_id=datasource_id,
            rows=[],
            user_id=user_id,
        )


def build_schema_vector_service(
    *,
    session: Any,
    llm_service: LLMService | None = None,
) -> ChatbiSchemaVectorService:
    """构造带当前 VECTOR_BACKEND 的 schema 向量服务。"""
    store_settings = build_chatbi_vector_settings()
    vector_store = ChatbiVectorStore(session=session, store_settings=store_settings)
    return ChatbiSchemaVectorService(
        vector_store=vector_store,
        llm_service=llm_service or LLMService(),
    )


def _build_schema_vector_text(table: dict[str, Any], column: dict[str, Any]) -> str:
    parts = [
        "kind=column",
        f"table={str(table.get('table_name') or '').strip()}",
        f"column={str(column.get('name') or '').strip()}",
    ]
    for key in ("type", "comment", "description", "constraints"):
        value = str(column.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    samples = _summarize_samples(column.get("samples"))
    if samples:
        parts.append(f"sample_values={samples}")
    fk_text = _foreign_key_text_for_column(table, str(column.get("name") or ""))
    if fk_text:
        parts.append(f"foreign_key={fk_text}")
    return " | ".join(parts)


def _build_table_vector_text(table: dict[str, Any]) -> str:
    table_name = str(table.get("table_name") or "").strip()
    if not table_name:
        return ""
    columns = table.get("columns") or []
    column_names: list[str] = []
    descriptions: list[str] = []
    sample_values: list[str] = []
    for col in columns:
        if not isinstance(col, dict):
            continue
        cname = str(col.get("name") or "").strip()
        if cname:
            column_names.append(cname)
        desc = str(col.get("description") or col.get("comment") or "").strip()
        if desc:
            descriptions.append(f"{cname}: {desc}" if cname else desc)
        sample = _summarize_samples(col.get("samples"), limit=3)
        if sample and cname:
            sample_values.append(f"{cname}=[{sample}]")
    parts = [
        "kind=table",
        f"table={table_name}",
    ]
    if column_names:
        parts.append(f"columns={', '.join(column_names)}")
    if descriptions:
        parts.append(f"column_descriptions={'; '.join(descriptions[:20])}")
    if sample_values:
        parts.append(f"sample_values={'; '.join(sample_values[:12])}")
    fks = table.get("foreign_keys") or []
    fk_parts: list[str] = []
    for fk in fks:
        if not isinstance(fk, dict):
            continue
        ref = fk.get("references") or {}
        if not isinstance(ref, dict):
            continue
        src = str(fk.get("column") or "").strip()
        rt = str(ref.get("table") or "").strip()
        rc = str(ref.get("column") or "").strip()
        if src and rt and rc:
            fk_parts.append(f"{src}->{rt}.{rc}")
    if fk_parts:
        parts.append(f"foreign_keys={', '.join(fk_parts)}")
    return " | ".join(parts)


def _summarize_samples(value: Any, *, limit: int = 8) -> str:
    if not isinstance(value, list):
        return ""
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        text = str(raw or "").strip()
        if not text:
            continue
        compact = " ".join(text.split())[:80]
        key = compact.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(compact)
        if len(out) >= limit:
            break
    return ", ".join(out)


def _foreign_key_text_for_column(table: dict[str, Any], column_name: str) -> str:
    column_name = column_name.strip()
    if not column_name:
        return ""
    for fk in table.get("foreign_keys") or []:
        if not isinstance(fk, dict):
            continue
        if str(fk.get("column") or "").strip() != column_name:
            continue
        ref = fk.get("references") or {}
        if not isinstance(ref, dict):
            return ""
        rt = str(ref.get("table") or "").strip()
        rc = str(ref.get("column") or "").strip()
        if rt and rc:
            return f"{column_name}->{rt}.{rc}"
    return ""


__all__ = ["ChatbiSchemaVectorService", "TABLE_VECTOR_COLUMN", "build_schema_vector_service"]
