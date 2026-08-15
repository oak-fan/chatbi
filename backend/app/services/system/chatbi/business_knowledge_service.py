"""ChatBI 业务知识业务编排。"""

from __future__ import annotations

from typing import Any

from cogmait_shared.core.api_codes import ErrorCode, HttpStatus

from ....constants.chatbi.datasource import CHATBI_VECTOR_DIMENSIONS
from ....constants.chatbi.query import CHATBI_BUSINESS_KNOWLEDGE_GLOBAL_LIMIT
from ....domain.system.chatbi import (
    ChatbiBusinessKnowledgeCreateInput,
    ChatbiBusinessKnowledgeDeleteInput,
    ChatbiBusinessKnowledgeKind,
    ChatbiBusinessKnowledgeListParams,
    ChatbiBusinessKnowledgeRecord,
    ChatbiBusinessKnowledgeScope,
    ChatbiBusinessKnowledgeUpdateInput,
)
from ....domain.system.llm import EmbeddingRequest
from ....repositories.system.chatbi import (
    ChatbiBusinessKnowledgeRepository,
    ChatbiDatasourceRepository,
)
from ..llm_service import LLMService, LLMServiceError
from ..service_error import ServiceError
from ..vector_store import VectorStoreError
from .vector import ChatbiVectorStore, build_chatbi_vector_settings


class ChatbiBusinessKnowledgeServiceError(ServiceError):
    """ChatBI 业务知识服务异常。"""

    @classmethod
    def bad_request(cls, message: str) -> ChatbiBusinessKnowledgeServiceError:
        return cls(
            message,
            status_code=HttpStatus.BAD_REQUEST,
            code=ErrorCode.PARAMS_INVALID,
        )

    @classmethod
    def not_found(cls, message: str = "记录不存在") -> ChatbiBusinessKnowledgeServiceError:
        return cls(
            message,
            status_code=HttpStatus.NOT_FOUND,
            code=ErrorCode.NOT_FOUND,
        )

    @classmethod
    def system_error(cls, message: str) -> ChatbiBusinessKnowledgeServiceError:
        return cls(
            message,
            status_code=HttpStatus.INTERNAL_ERROR,
            code=ErrorCode.SYSTEM_ERROR,
        )


class ChatbiBusinessKnowledgeService:
    """业务知识 CRUD 与同请求内向量同步。"""

    _SCOPE_VALUES = frozenset(scope.value for scope in ChatbiBusinessKnowledgeScope)
    _KIND_VALUES = frozenset(kind.value for kind in ChatbiBusinessKnowledgeKind)

    def __init__(
        self,
        *,
        unit_of_work: Any,
        llm_service: LLMService | None = None,
        vector_store: ChatbiVectorStore | None = None,
    ) -> None:
        self._uow = unit_of_work
        self._session = unit_of_work.session
        self._llm = llm_service or LLMService()
        self._repo = ChatbiBusinessKnowledgeRepository(self._session)
        self._ds_repo = ChatbiDatasourceRepository(self._session)
        self._vector_store = vector_store or ChatbiVectorStore(
            session=self._session,
            store_settings=build_chatbi_vector_settings(),
        )

    async def _commit(self) -> None:
        await self._uow.commit()

    async def _ensure_datasource(self, datasource_id: int, user_id: int) -> None:
        if await self._ds_repo.get_for_user(datasource_id, user_id) is None:
            raise ChatbiBusinessKnowledgeServiceError.not_found("数据源不存在")

    async def _sync_vector(self, record: ChatbiBusinessKnowledgeRecord, *, user_id: int) -> None:
        if record.scope != ChatbiBusinessKnowledgeScope.SYSTEM_INFERRED.value:
            try:
                await self._vector_store.soft_delete_business_knowledge_vector(
                    business_knowledge_id=record.id,
                    user_id=user_id,
                )
            except VectorStoreError as exc:
                raise ChatbiBusinessKnowledgeServiceError.system_error(
                    f"业务知识向量删除失败：{exc}"
                ) from exc
            return
        vector = await self._embed_content(record.content)
        try:
            await self._vector_store.upsert_business_knowledge_vector(
                business_knowledge_id=record.id,
                datasource_id=record.datasource_id,
                embedding=vector,
                user_id=user_id,
            )
        except VectorStoreError as exc:
            raise ChatbiBusinessKnowledgeServiceError.system_error(
                f"业务知识向量写入失败：{exc}"
            ) from exc

    async def _embed_content(self, content: str) -> list[float]:
        """业务知识只对系统推断内容生成向量，并在写入前校验维度。"""

        try:
            emb = await self._llm.aembedding(EmbeddingRequest(input_texts=[content]))
        except LLMServiceError as exc:
            raise ChatbiBusinessKnowledgeServiceError.system_error(
                f"业务知识向量化失败：{exc.message}"
            ) from exc
        if not emb.embeddings:
            raise ChatbiBusinessKnowledgeServiceError.system_error("业务知识向量化失败")
        vector = emb.embeddings[0]
        expected = CHATBI_VECTOR_DIMENSIONS
        if len(vector) != expected:
            raise ChatbiBusinessKnowledgeServiceError.bad_request(
                f"向量维度不匹配，期望 {expected}，实际 {len(vector)}"
            )
        return vector

    async def _sync_vector_and_commit(
        self,
        record: ChatbiBusinessKnowledgeRecord,
        *,
        user_id: int,
    ) -> ChatbiBusinessKnowledgeRecord:
        """同步业务知识向量后提交当前写入。"""

        await self._sync_vector(record, user_id=user_id)
        await self._commit()
        return record

    async def list_records(
        self,
        params: ChatbiBusinessKnowledgeListParams,
    ) -> tuple[list[ChatbiBusinessKnowledgeRecord], int]:
        self._validate_scope_filter(params.scope)
        self._validate_kind_filter(params.kind)
        return await self._repo.list_paginated(params)

    async def get_record(self, record_id: int, user_id: int) -> ChatbiBusinessKnowledgeRecord:
        record = await self._repo.get_for_user(record_id, user_id)
        if record is None:
            raise ChatbiBusinessKnowledgeServiceError.not_found()
        return record

    async def create_record(
        self, payload: ChatbiBusinessKnowledgeCreateInput
    ) -> ChatbiBusinessKnowledgeRecord:
        self._validate_scope(payload.scope)
        self._validate_kind(payload.kind)
        await self._ensure_datasource(payload.datasource_id, payload.user_id)
        record_id = await self._repo.create(payload)
        record = await self._repo.get_for_user(record_id, payload.user_id)
        if record is None:
            raise ChatbiBusinessKnowledgeServiceError.system_error("业务知识创建失败")
        return await self._sync_vector_and_commit(record, user_id=payload.user_id)

    async def update_record(
        self, payload: ChatbiBusinessKnowledgeUpdateInput
    ) -> ChatbiBusinessKnowledgeRecord:
        if "scope" in payload.provided_fields and payload.scope is not None:
            self._validate_scope(payload.scope)
        if "kind" in payload.provided_fields and payload.kind is not None:
            self._validate_kind(payload.kind)
        record = await self._repo.get_for_user(payload.record_id, payload.user_id)
        if record is None:
            raise ChatbiBusinessKnowledgeServiceError.not_found()
        if "datasource_id" in payload.provided_fields and payload.datasource_id is not None:
            await self._ensure_datasource(payload.datasource_id, payload.user_id)
        if not await self._repo.update(payload):
            raise ChatbiBusinessKnowledgeServiceError.not_found()
        record = await self._repo.get_for_user(payload.record_id, payload.user_id)
        if record is None:
            raise ChatbiBusinessKnowledgeServiceError.not_found()
        return await self._sync_vector_and_commit(record, user_id=payload.user_id)

    async def delete_record(self, payload: ChatbiBusinessKnowledgeDeleteInput) -> None:
        if await self._repo.get_for_user(payload.record_id, payload.user_id) is None:
            raise ChatbiBusinessKnowledgeServiceError.not_found()
        if not await self._repo.soft_delete(payload.record_id, payload.user_id):
            raise ChatbiBusinessKnowledgeServiceError.not_found()
        try:
            await self._vector_store.soft_delete_business_knowledge_vector(
                business_knowledge_id=payload.record_id,
                user_id=payload.user_id,
            )
        except VectorStoreError as exc:
            raise ChatbiBusinessKnowledgeServiceError.system_error(
                f"业务知识向量删除失败：{exc}"
            ) from exc
        await self._commit()

    @classmethod
    def _validate_scope(cls, scope: str) -> None:
        if scope not in cls._SCOPE_VALUES:
            raise ChatbiBusinessKnowledgeServiceError.bad_request("scope 取值不支持")

    @classmethod
    def _validate_kind(cls, kind: str) -> None:
        if kind not in cls._KIND_VALUES:
            raise ChatbiBusinessKnowledgeServiceError.bad_request("kind 取值不支持")

    @classmethod
    def _validate_scope_filter(cls, scope: str | None) -> None:
        if scope is not None:
            cls._validate_scope(scope)

    @classmethod
    def _validate_kind_filter(cls, kind: str | None) -> None:
        if kind is not None:
            cls._validate_kind(kind)

    async def _resolve_datasource_name(self, datasource_id: int) -> str:
        record = await self._ds_repo.get_by_id(datasource_id)
        if record is None:
            return str(datasource_id)
        name = (record.name or "").strip()
        return name or str(datasource_id)

    @staticmethod
    def _to_recall_hit(
        record: ChatbiBusinessKnowledgeRecord,
        *,
        datasource_name: str,
        score: float | None,
    ) -> dict[str, Any]:
        hit = {
            "business_knowledge_id": record.id,
            "score": score,
            "content": record.content,
            "kind": record.kind,
            "scope": record.scope,
            "datasource_id": record.datasource_id,
            "datasource_name": datasource_name,
        }
        hit["display_content"] = format_business_knowledge_display(hit)
        return hit

    async def _list_global_hits(
        self, *, datasource_id: int, datasource_name: str
    ) -> list[dict[str, Any]]:
        rows = await self._repo.list_by_datasource_and_scope(
            datasource_id,
            ChatbiBusinessKnowledgeScope.GLOBAL.value,
            limit=CHATBI_BUSINESS_KNOWLEDGE_GLOBAL_LIMIT,
        )
        return [
            self._to_recall_hit(row, datasource_name=datasource_name, score=None) for row in rows
        ]

    async def _search_inferred_hits(
        self,
        *,
        datasource_id: int,
        datasource_name: str,
        embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        hits = await self._vector_store.search_business_knowledge(
            datasource_id=datasource_id,
            embedding=embedding,
            top_k=top_k,
        )
        if not hits:
            return []
        hit_order = {hit.business_knowledge_id: hit.score for hit in hits}
        matched_ids = await self._repo.filter_ids_by_datasource(
            list(hit_order.keys()),
            datasource_id,
        )
        if not matched_ids:
            return []
        matched_ids.sort(key=lambda rid: hit_order.get(rid, 0.0), reverse=True)
        results: list[dict[str, Any]] = []
        for record_id in matched_ids:
            if len(results) >= top_k:
                break
            record = await self._repo.get_by_id(record_id)
            if record is None or record.scope != ChatbiBusinessKnowledgeScope.SYSTEM_INFERRED.value:
                continue
            results.append(
                self._to_recall_hit(
                    record,
                    datasource_name=datasource_name,
                    score=float(hit_order.get(record_id, 0.0)),
                )
            )
        return results

    async def search_business_knowledge_by_datasource(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """GLOBAL 全量注入；SYSTEM_INFERRED 走向量相似度过滤后取 Top-K。"""
        datasource_name = await self._resolve_datasource_name(datasource_id)
        global_hits = await self._list_global_hits(
            datasource_id=datasource_id,
            datasource_name=datasource_name,
        )
        inferred_hits = await self._search_inferred_hits(
            datasource_id=datasource_id,
            datasource_name=datasource_name,
            embedding=embedding,
            top_k=top_k,
        )
        seen: set[int] = set()
        merged: list[dict[str, Any]] = []
        for item in (*global_hits, *inferred_hits):
            rid = int(item["business_knowledge_id"])
            if rid in seen:
                continue
            seen.add(rid)
            merged.append(item)
        return merged


def format_business_knowledge_display(item: dict[str, Any]) -> str:
    """问数提示词 / SSE 展示：数据源名称 + 类型 + 正文。"""
    ds = str(item.get("datasource_name") or "").strip()
    kind = str(item.get("kind") or "").strip()
    body = str(item.get("content") or "").strip()
    prefix = f"【{ds}】" if ds else ""
    kind_part = f"[{kind}] " if kind else ""
    return f"{prefix}{kind_part}{body}".strip()


__all__ = [
    "ChatbiBusinessKnowledgeService",
    "ChatbiBusinessKnowledgeServiceError",
    "format_business_knowledge_display",
]
