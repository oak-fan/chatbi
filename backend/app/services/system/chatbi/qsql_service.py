"""ChatBI Q-SQL 业务编排。"""

from __future__ import annotations

from typing import Any, cast

from cogmait_shared.core.api_codes import ErrorCode, HttpStatus

from ....constants.chat import CHAT_MESSAGE_ROLE_SYSTEM, CHAT_MESSAGE_ROLE_USER
from ....constants.chatbi.datasource import CHATBI_VECTOR_DIMENSIONS
from ....domain.system.chatbi import (
    ChatbiQsqlCreateInput,
    ChatbiQsqlDeleteInput,
    ChatbiQsqlListParams,
    ChatbiQsqlRecord,
    ChatbiQsqlUpdateInput,
)
from ....domain.system.llm import CompletionRequest, CompletionResponse, EmbeddingRequest, Message
from ....repositories.system.chatbi import ChatbiDatasourceRepository, ChatbiQsqlRepository
from ..llm_service import LLMService, LLMServiceError
from ..service_error import ServiceError
from ..vector_store import VectorStoreError
from .datasource.connectors.postgresql import validate_readonly_postgres_sql
from .vector import ChatbiVectorStore, build_chatbi_vector_settings

_QSQL_DESCRIPTION_SYSTEM_PROMPT = (
    "你是 SQL 分析助手。根据用户给出的 SQL，用一句简短中文概括该查询的业务含义。"
    "只输出纯文本，不要 Markdown、不要 JSON、不要多余解释。"
)


class ChatbiQsqlServiceError(ServiceError):
    """ChatBI Q-SQL 服务异常。"""

    @classmethod
    def bad_request(cls, message: str) -> ChatbiQsqlServiceError:
        return cls(
            message,
            status_code=HttpStatus.BAD_REQUEST,
            code=ErrorCode.PARAMS_INVALID,
        )

    @classmethod
    def not_found(cls, message: str = "记录不存在") -> ChatbiQsqlServiceError:
        return cls(
            message,
            status_code=HttpStatus.NOT_FOUND,
            code=ErrorCode.NOT_FOUND,
        )

    @classmethod
    def system_error(cls, message: str) -> ChatbiQsqlServiceError:
        return cls(
            message,
            status_code=HttpStatus.INTERNAL_ERROR,
            code=ErrorCode.SYSTEM_ERROR,
        )


def _build_qsql_llm_metadata(
    *,
    user_id: int,
    datasource_id: int | None = None,
    record_id: int | None = None,
    operation: str,
) -> dict[str, Any]:
    trace_metadata: dict[str, str] = {
        "chatbi_source": "ai_service_chatbi",
        "operation": operation,
        "user_id": str(user_id),
    }
    if datasource_id is not None:
        trace_metadata["datasource_id"] = str(datasource_id)
    if record_id is not None:
        trace_metadata["record_id"] = str(record_id)
    return {
        "trace_user_id": str(user_id),
        "tags": ["ai-chatbi", operation],
        "langfuse_tags": ["ai-chatbi", operation],
        "trace_metadata": trace_metadata,
    }


def _build_qsql_embedding_text(question: str, simplified_description: str | None) -> str:
    """嵌入文本：question 或 question + 简述。"""
    if simplified_description and simplified_description.strip():
        return f"{question.strip()}\n\n{simplified_description.strip()}"
    return question.strip()


def _validate_qsql_body(sql_body: str) -> None:
    try:
        validate_readonly_postgres_sql(sql_body)
    except ValueError as exc:
        raise ChatbiQsqlServiceError.bad_request(str(exc)) from exc


async def _generate_qsql_simplified_description(
    *,
    llm_service: LLMService,
    sql_body: str,
    user_id: int,
    datasource_id: int,
) -> str:
    """从 SQL 生成 llm_simplified_description。"""
    req = CompletionRequest(
        messages=[
            Message(role=CHAT_MESSAGE_ROLE_SYSTEM, content=_QSQL_DESCRIPTION_SYSTEM_PROMPT),
            Message(role=CHAT_MESSAGE_ROLE_USER, content=sql_body),
        ],
        temperature=0.0,
        metadata=_build_qsql_llm_metadata(
            user_id=user_id,
            datasource_id=datasource_id,
            operation="qsql_description",
        ),
    )
    try:
        response = cast(CompletionResponse, await llm_service.acompletion(req))
    except LLMServiceError as exc:
        raise ChatbiQsqlServiceError.system_error(f"Q-SQL 简述生成失败：{exc.message}") from exc
    if not response.choices:
        raise ChatbiQsqlServiceError.system_error("Q-SQL 简述生成失败：模型返回为空")
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise ChatbiQsqlServiceError.system_error("Q-SQL 简述生成失败：模型返回空内容")
    return content.strip()


class ChatbiQsqlService:
    """Q-SQL CRUD 与同请求内向量同步。"""

    def __init__(
        self,
        *,
        unit_of_work: Any,
        llm_service: LLMService | None = None,
    ) -> None:
        self._uow = unit_of_work
        self._session = unit_of_work.session
        self._llm = llm_service or LLMService()
        self._qsql_repo = ChatbiQsqlRepository(self._session)
        self._ds_repo = ChatbiDatasourceRepository(self._session)
        self._vector_store = ChatbiVectorStore(
            session=self._session,
            store_settings=build_chatbi_vector_settings(),
        )

    async def _commit(self) -> None:
        await self._uow.commit()

    async def _ensure_datasource(self, datasource_id: int, user_id: int) -> None:
        if await self._ds_repo.get_for_user(datasource_id, user_id) is None:
            raise ChatbiQsqlServiceError.not_found("数据源不存在")

    async def _sync_vector(self, record: ChatbiQsqlRecord, *, user_id: int) -> None:
        text = _build_qsql_embedding_text(
            record.question,
            record.llm_simplified_description,
        )
        vector = await self._embed_text(text)
        try:
            await self._vector_store.upsert_qsql_vector(
                qsql_id=record.id,
                datasource_id=record.datasource_id,
                embedding=vector,
                user_id=user_id,
            )
        except VectorStoreError as exc:
            raise ChatbiQsqlServiceError.system_error(f"Q-SQL 向量写入失败：{exc}") from exc

    async def _embed_text(self, text: str) -> list[float]:
        """生成 Q-SQL 检索向量，并在写入前校验维度。"""

        try:
            emb = await self._llm.aembedding(EmbeddingRequest(input_texts=[text]))
        except LLMServiceError as exc:
            raise ChatbiQsqlServiceError.system_error(f"Q-SQL 向量化失败：{exc.message}") from exc
        if not emb.embeddings:
            raise ChatbiQsqlServiceError.system_error("Q-SQL 向量化失败")
        vector = emb.embeddings[0]
        expected = CHATBI_VECTOR_DIMENSIONS
        if len(vector) != expected:
            raise ChatbiQsqlServiceError.bad_request(
                f"向量维度不匹配，期望 {expected}，实际 {len(vector)}"
            )
        return vector

    async def _generate_description_sync_vector_and_commit(
        self,
        *,
        record_id: int,
        user_id: int,
        datasource_id: int,
        sql_body: str,
        missing_message: str | None = None,
    ) -> ChatbiQsqlRecord:
        """刷新 Q-SQL 简述、同步检索向量，并提交本次创建或更新。"""

        description = await _generate_qsql_simplified_description(
            llm_service=self._llm,
            sql_body=sql_body,
            user_id=user_id,
            datasource_id=datasource_id,
        )
        await self._qsql_repo.update_description(
            record_id,
            description=description,
            user_id=user_id,
        )
        record = await self._qsql_repo.get_for_user(record_id, user_id)
        if record is None:
            if missing_message is not None:
                raise ChatbiQsqlServiceError.system_error(missing_message)
            raise ChatbiQsqlServiceError.not_found()
        await self._sync_vector(record, user_id=user_id)
        await self._commit()
        return record

    async def list_qsql(self, params: ChatbiQsqlListParams) -> tuple[list[ChatbiQsqlRecord], int]:
        return await self._qsql_repo.list_paginated(params)

    async def get_qsql(self, record_id: int, user_id: int) -> ChatbiQsqlRecord:
        record = await self._qsql_repo.get_for_user(record_id, user_id)
        if record is None:
            raise ChatbiQsqlServiceError.not_found()
        return record

    async def create_qsql(self, payload: ChatbiQsqlCreateInput) -> ChatbiQsqlRecord:
        await self._ensure_datasource(payload.datasource_id, payload.user_id)
        _validate_qsql_body(payload.sql_body)
        record_id = await self._qsql_repo.create(payload)
        return await self._generate_description_sync_vector_and_commit(
            record_id=record_id,
            user_id=payload.user_id,
            datasource_id=payload.datasource_id,
            sql_body=payload.sql_body,
            missing_message="Q-SQL 创建失败",
        )

    async def update_qsql(self, payload: ChatbiQsqlUpdateInput) -> ChatbiQsqlRecord:
        record = await self._qsql_repo.get_for_user(payload.record_id, payload.user_id)
        if record is None:
            raise ChatbiQsqlServiceError.not_found()
        if "sql_body" in payload.provided_fields and payload.sql_body is not None:
            _validate_qsql_body(payload.sql_body)
        if not await self._qsql_repo.update(payload):
            raise ChatbiQsqlServiceError.not_found()
        record = await self._qsql_repo.get_for_user(payload.record_id, payload.user_id)
        if record is None:
            raise ChatbiQsqlServiceError.not_found()
        if "sql_body" in payload.provided_fields:
            return await self._generate_description_sync_vector_and_commit(
                record_id=payload.record_id,
                user_id=payload.user_id,
                datasource_id=record.datasource_id,
                sql_body=record.sql_body,
            )
        await self._sync_vector(record, user_id=payload.user_id)
        await self._commit()
        return record

    async def delete_qsql(self, payload: ChatbiQsqlDeleteInput) -> None:
        if await self._qsql_repo.get_for_user(payload.record_id, payload.user_id) is None:
            raise ChatbiQsqlServiceError.not_found()
        if not await self._qsql_repo.soft_delete(payload.record_id, payload.user_id):
            raise ChatbiQsqlServiceError.not_found()
        try:
            await self._vector_store.soft_delete_qsql_vector(
                qsql_id=payload.record_id,
                user_id=payload.user_id,
            )
        except VectorStoreError as exc:
            raise ChatbiQsqlServiceError.system_error(f"Q-SQL 向量删除失败：{exc}") from exc
        await self._commit()


__all__ = ["ChatbiQsqlService", "ChatbiQsqlServiceError"]
