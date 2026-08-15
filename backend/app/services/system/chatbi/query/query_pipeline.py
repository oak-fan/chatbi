"""ChatBI 问数 SSE 编排主流程。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from cogmait_shared.core.api_codes import ErrorCode

from .....constants.chat import (
    CHAT_MESSAGE_ROLE_ASSISTANT,
    CHAT_MESSAGE_ROLE_SYSTEM,
    CHAT_MESSAGE_ROLE_USER,
    CHAT_MESSAGE_STATUS_FAILED,
    CHAT_MESSAGE_STATUS_SUCCESS,
)
from .....constants.chatbi.query import (
    CHATBI_BUSINESS_KNOWLEDGE_TOP_K,
    CHATBI_CLARIFICATION_SKIPPED_MARKER,
    CHATBI_QSQL_RECALL_CANDIDATE_TOP_N,
    CHATBI_QSQL_RECALL_FILTERED_CANDIDATE_TOP_N,
    CHATBI_QSQL_RECALL_TOP_N,
    CHATBI_QUERY_DATASOURCE_CANDIDATE_LIMIT,
    CHATBI_QUERY_HISTORY_LIMIT,
    CHATBI_QUERY_OUTCOME_LLM_ERROR,
    CHATBI_QUERY_OUTCOME_MISSING_DATASOURCE,
    CHATBI_QUERY_OUTCOME_SCHEMA_NOT_READY,
    CHATBI_QUERY_OUTCOME_SERVICE_ERROR,
    CHATBI_QUERY_OUTCOME_SQL_EXECUTE_FAILED,
    CHATBI_QUERY_OUTCOME_SUCCESS,
    CHATBI_QUERY_OUTCOME_TEXT2SQL_FAILED,
    CHATBI_QUERY_OUTCOME_UNHANDLED_ERROR,
    CHATBI_RESULT_PREVIEW_MAX_ROWS,
    CHATBI_SCHEMA_SELECT_TOP_K,
    CHATBI_SQL_FIX_MAX_ATTEMPTS,
    CHATBI_SSE_BUSINESS_KNOWLEDGE_RECALL,
    CHATBI_SSE_CLARIFICATION_REQUIRED,
    CHATBI_SSE_DATA,
    CHATBI_SSE_FAILED,
    CHATBI_SSE_INTENT,
    CHATBI_SSE_QSQL_RECALL,
    CHATBI_SSE_RAG_KNOWLEDGE_RECALL,
    CHATBI_SSE_REWRITTEN_QUESTION,
    CHATBI_SSE_SCHEMA_LINKING,
    CHATBI_SSE_SCHEMA_SELECTED,
    CHATBI_SSE_SQL,
    CHATBI_SSE_SQL_CANDIDATES,
    CHATBI_SSE_SQL_GROUP_AUDIT,
    CHATBI_SSE_SQL_VALIDATE,
    CHATBI_SSE_STARTED,
    CHATBI_SSE_SUMMARY,
    CHATBI_SSE_VALUE_FOUNDING,
    CHATBI_SSE_VALUE_SEARCH,
    CHATBI_SUMMARY_MISSING_DATASOURCE,
    CHATBI_SUMMARY_PREVIEW_MAX_ROWS,
)
from .....domain.system.chatbi.datasource import ChatbiDatasourceRecord
from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from .....domain.system.chatbi.qsql import (
    QSQL_GLOBAL_DATASOURCE_ID,
    QSQL_SCOPE_DATASOURCE,
    QSQL_SCOPE_GLOBAL,
)
from .....domain.system.chatbi.query import (
    ChatbiQueryIntent,
    ChatbiQueryRunInput,
    ChatbiQueryStreamEvent,
)
from .....domain.system.llm import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingRequest,
    Message,
)
from .....observability import ObservabilityProvider
from .....repositories.system.chat import ChatRepository
from .....repositories.system.chatbi import (
    ChatbiDatasourceRepository,
    ChatbiQsqlRepository,
    ChatbiQueryLogRepository,
)
from .....repositories.system.chatbi.benchmark import ChatbiBenchmarkRepository
from ...llm_service import LLMService, LLMServiceError
from ...rewrite import RewriteService
from ...rewrite.context import RewriteInput, RewriteMessage, RewriteStrategyType
from ...service_error import ServiceError
from ..business_knowledge_service import ChatbiBusinessKnowledgeService
from ..datasource.credential_encryption_service import ChatbiCredentialEncryptionService
from ..datasource.db_connection_service import ChatbiDbConnectionService
from ..datasource_errors import ChatbiDatasourceServiceError
from ..multi_agent.tools import MultiAgentToolbox
from ..group_by_auditor import GroupByAuditorRunner
from ..query_errors import ChatbiQueryServiceError
from ..value_index import ChatbiValueIndexStore, format_value_search_hits_for_text2sql
from ..vector import ChatbiVectorStore, build_chatbi_vector_settings
from .agentar import (
    build_agentar_schema_views,
    dedupe_sql_candidates,
    fallback_select_sql_candidate,
    group_sql_candidates,
    try_consensus_sql_candidate,
)
from .agentar.types import AgentarSchemaView, SqlCandidate, SqlCandidateGroup
from .clarification_store import ChatbiClarificationStore
from .persistence import ChatbiQueryPersistence
from .prompts import (
    INTENT_SYSTEM,
    SQL_FIX_ERROR_SYSTEM,
    SQL_VALIDATE_SYSTEM,
    SUMMARY_SYSTEM,
    build_agentar_sql_selector_system_prompt,
    build_agentar_sql_selector_user_content,
    build_clarification_dialogue_for_text2sql,
    build_effective_question_after_clarification,
    build_intent_user_content,
    build_sql_fix_user_content,
    build_sql_validate_user_content,
    build_summary_user_content,
    build_text2sql_system_prompt,
    build_text2sql_user_content,
    datasource_description_from_db_schema,
    extract_sql_from_llm,
    intent_detail_from_result,
    json_safe_rows,
    parse_agentar_sql_selector_response,
    parse_intent_response,
    parse_text2sql_response,
    table_names_from_db_schema,
    text2sql_clarification_kwargs,
)
from .qsql_retrieval import (
    GlobalQsqlScopeFilter,
    QsqlRetrievalCandidate,
    global_qsql_matches_scope,
    rank_qsql_candidates,
)
from .runtime import (
    DatasourceResolution as _DatasourceResolution,
    RunContext as _RunContext,
    RunMeta as _RunMeta,
    RunState as _RunState,
    SchemaSelectionResult as _SchemaSelectionResult,
    SqlExecutionResult as _SqlExecutionResult,
)
from .schema_select_service import ChatbiSchemaSelectService
from .sql_executor import ChatbiSqlExecutor
from .sql_validate import SqlValidateExecution, SqlValidateResult, build_sql_validate_context
from .value_founding import (
    VALUE_FOUNDING_SYSTEM,
    ValueFoundingMatcher,
    build_value_founding_user_content,
    format_value_founding_matches_for_text2sql,
    parse_value_founding_response,
)

AGENTAR_CANDIDATE_PROBE_MAX_ROWS = 20


class ChatbiQueryPipeline:
    """问数主链路编排。"""

    def __init__(
        self,
        *,
        unit_of_work: Any,
        redis: Any,
        llm_service: LLMService,
        rewrite_service: RewriteService,
        observability: ObservabilityProvider,
        encryption_key: str | None,
    ) -> None:
        session = unit_of_work.session
        self._llm = llm_service
        self._rewrite = rewrite_service
        self._observability = observability
        self._ds_repo = ChatbiDatasourceRepository(session)
        self._qsql_repo = ChatbiQsqlRepository(session)
        self._benchmark_repo = ChatbiBenchmarkRepository(session)
        self._chat_repo = ChatRepository(session)
        self._query_persistence = ChatbiQueryPersistence(
            unit_of_work=unit_of_work,
            chat_repo=self._chat_repo,
            query_log_repo=ChatbiQueryLogRepository(session),
            observability=observability,
        )
        self._clarification = ChatbiClarificationStore(redis=redis)
        self._vector_store = ChatbiVectorStore(
            session=session,
            store_settings=build_chatbi_vector_settings(),
        )
        self._schema_select = ChatbiSchemaSelectService(
            session=session,
            llm_service=llm_service,
            vector_store=self._vector_store,
            datasource_repo=self._ds_repo,
        )
        self._value_index = ChatbiValueIndexStore()
        self._biz_kn = ChatbiBusinessKnowledgeService(
            unit_of_work=unit_of_work,
            llm_service=llm_service,
            vector_store=self._vector_store,
        )
        encryption = ChatbiCredentialEncryptionService(key_material=encryption_key)
        db_conn = ChatbiDbConnectionService(
            datasource_repo=self._ds_repo,
            encryption=encryption,
        )
        self._sql_executor = ChatbiSqlExecutor(db_connection=db_conn)
        self._db_conn = db_conn
        self._encryption_key = encryption_key
        self._active_completion_model: str | None = None

    async def run_stream(
        self,
        payload: ChatbiQueryRunInput,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """按固定 SSE 顺序编排单次 ChatBI 问数。"""
        self._active_completion_model = payload.options.completion_model
        ctx = _RunContext(
            payload=payload,
            state=_RunState.from_payload(payload),
            meta=_RunMeta(request_id=payload.request_id or str(uuid.uuid4())),
        )

        try:
            async for event in self._run_stream_body(ctx):
                yield event
        except ServiceError as exc:
            async for failed_event in self._stream_failed_and_persist(
                ctx,
                message=exc.message,
                detail=str(exc),
                outcome=CHATBI_QUERY_OUTCOME_SERVICE_ERROR,
            ):
                yield failed_event
        except (LLMServiceError,) as exc:
            async for failed_event in self._stream_failed_and_persist(
                ctx,
                message=exc.message,
                detail=str(exc),
                outcome=CHATBI_QUERY_OUTCOME_LLM_ERROR,
            ):
                yield failed_event
        except Exception as exc:
            async for failed_event in self._stream_failed_and_persist(
                ctx,
                message="问数处理失败",
                detail=str(exc),
                outcome=CHATBI_QUERY_OUTCOME_UNHANDLED_ERROR,
            ):
                yield failed_event

    async def _run_stream_body(
        self,
        ctx: _RunContext,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """保持对外事件顺序的主链路阶段编排。"""
        with self._observability.trace(
            "ai.chatbi.run",
            metadata={"request_id": ctx.meta.request_id, "user_id": str(ctx.payload.user_id)},
        ):
            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_STARTED, request_id=ctx.meta.request_id)

            rewritten_event = await self._prepare_question_context(ctx)
            if rewritten_event is not None:
                yield rewritten_event

            available_datasources = await self._prepare_datasource_candidates(ctx)
            if not available_datasources:
                if ctx.state.bound_datasource_id is not None:
                    resolution = await self._resolve_ready_datasource(ctx)
                    if resolution.terminal_summary is not None:
                        async for terminal_event in self._stream_terminal_summary_for_state(
                            ctx,
                            summary=resolution.terminal_summary,
                            outcome=resolution.outcome,
                        ):
                            yield terminal_event
                        return
                async for terminal_event in self._stream_terminal_summary_for_state(
                    ctx,
                    summary=CHATBI_SUMMARY_MISSING_DATASOURCE,
                    outcome=CHATBI_QUERY_OUTCOME_MISSING_DATASOURCE,
                ):
                    yield terminal_event
                return

            recall_question = ctx.state.snapshot_rewritten_question
            if ctx.payload.options.business_knowledge_recall_enabled:
                with self._observability.span("ai.chatbi.business_knowledge_recall"):
                    biz_kn_intent, biz_kn_by_datasource = (
                        await self._recall_business_knowledge_for_candidates(
                            candidate_datasources=ctx.state.candidate_datasources,
                            question=recall_question,
                            meta=ctx.meta,
                        )
                    )
            else:
                biz_kn_intent = []
                biz_kn_by_datasource = {}
            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_BUSINESS_KNOWLEDGE_RECALL,
                business_knowledge_hits=biz_kn_intent,
            )

            await self._resolve_intent(
                ctx,
                business_knowledge=biz_kn_intent,
            )

            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_INTENT,
                intent=ctx.state.intent_value,
                intent_detail=ctx.state.intent_detail,
                missing_datasource=False,
            )

            async for event in self._stream_after_intent(
                ctx,
                recall_question=recall_question,
                business_knowledge_by_datasource=biz_kn_by_datasource,
            ):
                yield event

    async def _stream_after_intent(
        self,
        ctx: _RunContext,
        *,
        recall_question: str,
        business_knowledge_by_datasource: dict[int, list[dict[str, Any]]],
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """处理意图之后的澄清终态、选源和 SQL 查询链路。"""
        if ctx.state.intent_value == ChatbiQueryIntent.UNRELATED.value:
            async for event in self._stream_terminal_summary_for_state(
                ctx,
                summary=self._unrelated_summary(ctx.state.intent_result),
                outcome=ChatbiQueryIntent.UNRELATED.value,
            ):
                yield event
            return

        if ctx.state.intent_value == ChatbiQueryIntent.CLARIFICATION.value:
            async for event in self._stream_clarification_required(ctx):
                yield event
            return

        resolution = await self._resolve_ready_datasource(ctx)
        if resolution.terminal_summary is not None:
            async for event in self._stream_terminal_summary_for_state(
                ctx,
                summary=resolution.terminal_summary,
                outcome=resolution.outcome,
            ):
                yield event
            return

        async for event in self._stream_sql_query(
            ctx,
            ds_record=cast(ChatbiDatasourceRecord, resolution.record),
            recall_question=recall_question,
            business_knowledge_by_datasource=business_knowledge_by_datasource,
        ):
            yield event

    async def _resolve_ready_datasource(
        self,
        ctx: _RunContext,
    ) -> _DatasourceResolution:
        """解析意图中的数据源，并判断是否具备可问数的 schema。"""
        ctx.state.datasource_id = self._resolve_datasource_from_intent(
            ctx.state.intent_result,
            ctx.state.candidate_datasources,
            ctx.state.bound_datasource_id,
        )
        if ctx.state.datasource_id is None:
            return _DatasourceResolution(
                terminal_summary=CHATBI_SUMMARY_MISSING_DATASOURCE,
                outcome=CHATBI_QUERY_OUTCOME_MISSING_DATASOURCE,
            )

        self._set_pipeline_question(ctx)
        ds_record = await self._ds_repo.get_for_user(
            ctx.state.datasource_id,
            ctx.payload.user_id,
        )
        if ds_record is None:
            raise ChatbiQueryServiceError.not_found("数据源不存在或无权访问")
        self._observability.update_current_trace(
            metadata={"datasource_id": str(ctx.state.datasource_id)}
        )
        if not ds_record.db_schema:
            return _DatasourceResolution(
                terminal_summary="数据源尚未完成结构预处理，无法问数。",
                outcome=CHATBI_QUERY_OUTCOME_SCHEMA_NOT_READY,
            )
        return _DatasourceResolution(record=ds_record)

    async def _stream_sql_query(
        self,
        ctx: _RunContext,
        *,
        ds_record: ChatbiDatasourceRecord,
        recall_question: str,
        business_knowledge_by_datasource: dict[int, list[dict[str, Any]]],
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """执行 schema、Q-SQL、Text2SQL、SQL 执行、总结和持久化阶段。"""
        datasource_id = cast(int, ctx.state.datasource_id)
        schema_text = await self._select_schema_and_stream_event(
            ctx,
            ds_record=ds_record,
            datasource_id=datasource_id,
        )
        if schema_text.linking_event is not None:
            yield schema_text.linking_event
        yield schema_text.event

        if ctx.payload.options.qsql_recall_enabled:
            qsql_examples, qsql_event = await self._recall_qsql_and_build_event(
                datasource_id=datasource_id,
                question=ctx.state.pipeline_question,
                meta=ctx.meta,
            )
        else:
            qsql_examples = []
            qsql_event = ChatbiQueryStreamEvent(event=CHATBI_SSE_QSQL_RECALL, qsql_hits=[])
        yield qsql_event

        rag_knowledge_hits: list[dict[str, Any]] = []
        if ctx.payload.options.rag_enabled:
            try:
                rag_knowledge_hits = await self._run_rag_knowledge_search(
                    ds_record=ds_record,
                    question=ctx.state.pipeline_question,
                )
            except Exception as exc:
                self._observability.update_current_trace(
                    metadata={"rag_knowledge_recall_error": str(exc)[:500]},
                )
                rag_knowledge_hits = []
            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_RAG_KNOWLEDGE_RECALL,
                rag_knowledge_hits=rag_knowledge_hits,
            )

        if ctx.payload.options.business_knowledge_recall_enabled:
            biz_kn_final = await self._business_knowledge_for_sql(
                datasource_id=datasource_id,
                question=ctx.state.pipeline_question,
                recall_question=recall_question,
                business_knowledge_by_datasource=business_knowledge_by_datasource,
                meta=ctx.meta,
            )
        else:
            biz_kn_final = []
        text2sql_clarification = text2sql_clarification_kwargs(
            clarification_question=ctx.state.clarification_question,
            user_clarification_answer=ctx.state.user_clarification_answer,
        )
        value_founding_text, value_events = await self._run_value_founding(
            ctx,
            ds_record=ds_record,
            schema_text=schema_text.text,
            schema=schema_text.schema,
        )
        ctx.state.value_founding_text = value_founding_text
        for event in value_events:
            yield event
        text2sql_out, candidate_event = await self._generate_sql_with_timing(
            ctx,
            ds_record=ds_record,
            schema_selection=schema_text,
            qsql_examples=qsql_examples,
            business_knowledge=biz_kn_final,
            text2sql_clarification=text2sql_clarification,
            rag_knowledge_hits=rag_knowledge_hits,
        )
        if candidate_event is not None:
            yield candidate_event

        sql = str(text2sql_out.get("sql") or "").strip()
        if not sql:
            summary = self._text2sql_terminal_summary(text2sql_out)
            async for event in self._stream_terminal_summary_for_state(
                ctx,
                summary=summary,
                outcome=CHATBI_QUERY_OUTCOME_TEXT2SQL_FAILED,
            ):
                yield event
            return

        yield ChatbiQueryStreamEvent(event=CHATBI_SSE_SQL, sql=sql)
        ctx.state.final_sql = sql
        if ctx.payload.options.sql_validate_enabled:
            validate_result = await self._validate_sql_after_generation(
                ctx,
                ds_record=ds_record,
                sql=sql,
                schema=schema_text.schema,
                schema_text=schema_text.text,
                text2sql_clarification=text2sql_clarification,
            )
            yield ChatbiQueryStreamEvent(
                event=CHATBI_SSE_SQL_VALIDATE,
                sql=validate_result.validated_sql,
                validation=validate_result.to_validation_payload(),
            )
            if validate_result.changed:
                sql = validate_result.validated_sql
                ctx.state.final_sql = sql
                yield ChatbiQueryStreamEvent(event=CHATBI_SSE_SQL, sql=sql)

        if ctx.payload.options.group_by_audit_enabled:
            audit_final_sql: str | None = None
            async for audit_event in self._run_group_by_audit(
                ctx,
                sql=sql,
                ds_record=ds_record,
                schema_text=schema_text.text,
            ):
                yield audit_event
                phase = audit_event.group_audit.get("phase")
                if phase == "final":
                    candidate = str(audit_event.group_audit.get("sql") or "")
                    if candidate:
                        audit_final_sql = candidate
            if audit_final_sql and audit_final_sql != sql:
                sql = audit_final_sql
                ctx.state.final_sql = sql
                yield ChatbiQueryStreamEvent(event=CHATBI_SSE_SQL, sql=sql)

        execution_result, fixed_sql = await self._execute_sql_with_optional_fix(
            ctx,
            sql=sql,
            schema_text=schema_text.text,
            text2sql_clarification=text2sql_clarification,
        )
        if fixed_sql is not None:
            ctx.state.final_sql = fixed_sql
            yield ChatbiQueryStreamEvent(event=CHATBI_SSE_SQL, sql=fixed_sql, sql_fixed=True)

        if execution_result.error:
            async for event in self._stream_failed_and_persist(
                ctx,
                message="SQL 执行失败",
                detail=execution_result.error,
                outcome=CHATBI_QUERY_OUTCOME_SQL_EXECUTE_FAILED,
                rewritten_question=ctx.state.pipeline_question,
            ):
                yield event
            return

        async for event in self._stream_data_summary_and_persist(
            ctx,
            sql=sql,
            execution_result=execution_result,
        ):
            yield event

    @staticmethod
    def _unrelated_summary(intent_result: dict[str, Any]) -> str:
        summary = str(
            intent_result.get("brief_explanation") or intent_result.get("message") or ""
        ).strip()
        return summary or "您的问题与当前可用数据源无关，无法查询。"

    async def _stream_clarification_required(
        self,
        ctx: _RunContext,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """输出澄清事件；客户端拿 token 后会再次进入同一问数链路。"""
        token = await self._save_clarification_request(ctx)
        yield ChatbiQueryStreamEvent(
            event=CHATBI_SSE_CLARIFICATION_REQUIRED,
            clarification_token=token,
            question=str(ctx.state.intent_result.get("clarification_question", "")),
            options=list(ctx.state.intent_result.get("options") or []),
        )
        self._trace_terminal_outcome(ctx.meta, ChatbiQueryIntent.CLARIFICATION.value)
        yield ctx.meta.to_completed_stream_event()

    @staticmethod
    def _parse_db_schema(raw_schema: dict[str, Any]) -> ChatbiDbSchemaRecord:
        try:
            return ChatbiDbSchemaRecord.from_json_dict(raw_schema)
        except ValueError as exc:
            raise ChatbiQueryServiceError.bad_request("数据源结构不可用") from exc

    @staticmethod
    def _count_schema_tables(raw_schema: dict[str, Any]) -> int:
        tables = raw_schema.get("tables")
        if isinstance(tables, list):
            return len(tables)
        return 0

    @staticmethod
    def _sql_fix_max_attempts(ctx: _RunContext) -> int:
        configured = ctx.payload.options.sql_fix_max_attempts
        if configured is not None:
            return configured
        return CHATBI_SQL_FIX_MAX_ATTEMPTS

    @staticmethod
    def _schema_selection_from_record(
        schema: ChatbiDbSchemaRecord,
        *,
        schema_fields: list[str] | None = None,
        hints_text: str | None = None,
        linking_event: ChatbiQueryStreamEvent | None = None,
    ) -> _SchemaSelectionResult:
        full_fields = [
            f"{table.table_name}.{column.name}"
            for table in schema.tables
            for column in table.columns
        ]
        schema_text = schema.build_llm_context_summary()
        if hints_text:
            schema_text = f"{schema_text}\n\n{hints_text.strip()}"
        return _SchemaSelectionResult(
            text=schema_text,
            event=ChatbiQueryStreamEvent(
                event=CHATBI_SSE_SCHEMA_SELECTED,
                schema_fields=schema_fields or full_fields,
            ),
            schema=schema,
            linking_event=linking_event,
        )

    async def _select_schema_and_stream_event(
        self,
        ctx: _RunContext,
        *,
        ds_record: ChatbiDatasourceRecord,
        datasource_id: int,
    ) -> _SchemaSelectionResult:
        """选择 Text2SQL 可见 schema，并构造对应 SSE 事件。"""
        raw_schema = ds_record.db_schema
        if not isinstance(raw_schema, dict):
            raise ChatbiQueryServiceError.bad_request("数据源结构未就绪")

        full_schema = self._parse_db_schema(raw_schema)
        full_fields = [
            f"{table.table_name}.{column.name}"
            for table in full_schema.tables
            for column in table.columns
        ]
        table_count = len(full_schema.tables)
        if not ctx.payload.options.schema_selection_enabled:
            return self._schema_selection_from_record(
                full_schema,
                linking_event=self._build_schema_linking_event(
                    mode="disabled",
                    enabled=False,
                    table_count=table_count,
                    fields=[],
                    small_schema_threshold=ctx.payload.options.schema_small_table_threshold,
                ),
            )

        if table_count <= ctx.payload.options.schema_small_table_threshold:
            return self._schema_selection_from_record(
                full_schema,
                linking_event=self._build_schema_linking_event(
                    mode="small_schema_guard",
                    enabled=True,
                    table_count=table_count,
                    fields=full_fields,
                    small_schema_threshold=ctx.payload.options.schema_small_table_threshold,
                    small_schema_guard=True,
                ),
            )

        top_k = ctx.payload.options.schema_top_k or CHATBI_SCHEMA_SELECT_TOP_K
        t0 = time.perf_counter()
        try:
            with self._observability.span("ai.chatbi.schema_select"):
                linking = await self._schema_select.link_schema(
                    user_id=ctx.payload.user_id,
                    datasource_id=datasource_id,
                    question_text=ctx.state.pipeline_question,
                    top_k=top_k,
                    use_rerank=True,
                    db_schema=raw_schema,
                )
        except Exception as exc:
            self._observability.update_current_trace(
                metadata={"schema_linking_error": str(exc)[:500]}
            )
            return self._schema_selection_from_record(
                full_schema,
                linking_event=self._build_schema_linking_event(
                    mode="fallback",
                    enabled=True,
                    table_count=table_count,
                    fields=[],
                    top_k=top_k,
                    small_schema_threshold=ctx.payload.options.schema_small_table_threshold,
                    error=str(exc)[:500],
                ),
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        ctx.meta.schema_select_latency_ms = latency_ms
        ctx.state.schema_linking_result = linking
        hints_text = str(linking.get("hints_text") or "").strip() or None
        schema_fields = [
            str(item)
            for item in linking.get("schema_fields", [])
            if isinstance(item, str) and item.strip()
        ]
        return self._schema_selection_from_record(
            full_schema,
            schema_fields=schema_fields or None,
            hints_text=hints_text,
            linking_event=self._build_schema_linking_event(
                mode="linked",
                enabled=True,
                table_count=table_count,
                fields=schema_fields,
                top_k=top_k,
                latency_ms=latency_ms,
                small_schema_threshold=ctx.payload.options.schema_small_table_threshold,
                table_candidates=linking.get("table_candidates"),
                column_candidates=linking.get("column_candidates"),
                hints_injected=bool(hints_text),
            ),
        )

    @staticmethod
    def _build_schema_linking_event(
        *,
        mode: str,
        enabled: bool,
        table_count: int,
        fields: list[str],
        top_k: int | None = None,
        latency_ms: int | None = None,
        small_schema_threshold: int | None = None,
        small_schema_guard: bool = False,
        table_candidates: Any = None,
        column_candidates: Any = None,
        hints_injected: bool = False,
        error: str | None = None,
    ) -> ChatbiQueryStreamEvent:
        payload: dict[str, Any] = {
            "mode": mode,
            "enabled": enabled,
            "table_count": table_count,
            "field_count": len(fields),
            "fields": fields,
            "top_k": top_k,
            "latency_ms": latency_ms,
            "small_schema_threshold": small_schema_threshold,
            "small_schema_guard": small_schema_guard,
            "table_candidates": table_candidates if isinstance(table_candidates, list) else [],
            "column_candidates": column_candidates if isinstance(column_candidates, list) else [],
            "hints_injected": hints_injected,
            "selected_schema_policy": "full_schema_with_linking_hints" if hints_injected else "full_schema",
        }
        if error:
            payload["error_message"] = error
        return ChatbiQueryStreamEvent(
            event=CHATBI_SSE_SCHEMA_LINKING,
            schema_linking=payload,
        )

    async def _run_rag_knowledge_search(
        self,
        *,
        ds_record: ChatbiDatasourceRecord,
        question: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search the BIRD knowledge store for schema-relevant chunks."""
        if not ds_record.db_schema:
            return []
        schema = ChatbiDbSchemaRecord.from_json_dict(ds_record.db_schema)
        toolbox = MultiAgentToolbox(
            llm_service=self._llm,
            db_connection=self._db_conn,
            datasource_id=cast(int, ds_record.id),
            datasource_owner_id=None,
            db_name=schema.database,
            db_type=str(ds_record.connector_type or "SQLite").upper(),
            schema=schema,
        )
        try:
            return await toolbox.knowledge_search(question, top_k=top_k)
        finally:
            await toolbox.close()

    async def _run_value_founding(
        self,
        ctx: _RunContext,
        *,
        ds_record: ChatbiDatasourceRecord,
        schema_text: str,
        schema: Any | None,
    ) -> tuple[str | None, list[ChatbiQueryStreamEvent]]:
        if not (
            ctx.payload.options.value_founding_enabled
            or ctx.payload.options.value_search_enabled
        ):
            return None, []
        if not isinstance(schema, ChatbiDbSchemaRecord):
            return None, []
        datasource_id = cast(int, ctx.state.datasource_id)
        t0 = time.perf_counter()
        try:
            db_type = str(ds_record.connector_type or "SQLite")
            with self._observability.span("ai.chatbi.value_founding.extract"):
                content = await self._llm_completion(
                    system=VALUE_FOUNDING_SYSTEM,
                    user=build_value_founding_user_content(
                        question=ctx.state.pipeline_question,
                        db_type=db_type,
                        schema_text=schema_text,
                    ),
                        meta=ctx.meta,
                        temperature=0.0,
                    )
            all_literals = parse_value_founding_response(
                content,
                schema=schema,
                require_columns=False,
            )
            literal_dicts = [{"value": lit.value, "columns": lit.columns} for lit in all_literals]
            events: list[ChatbiQueryStreamEvent] = []
            context_parts: list[str] = []
            matches = []
            if ctx.payload.options.value_founding_enabled:
                literals_with_columns = [lit for lit in all_literals if lit.columns]

                async def execute_distinct_values(
                    sql: str,
                    max_rows: int,
                ) -> tuple[list[str], list[dict[str, Any]], bool]:
                    return await self._sql_executor.execute(
                        datasource_id=datasource_id,
                        user_id=ctx.payload.user_id,
                        sql=sql,
                        max_rows=max_rows,
                    )

                matcher = ValueFoundingMatcher(execute_sql=execute_distinct_values)
                with self._observability.span("ai.chatbi.value_founding.match"):
                    matches = await matcher.find_matches(literals=literals_with_columns, schema=schema)
                founding_text = format_value_founding_matches_for_text2sql(matches)
                if founding_text:
                    context_parts.append(founding_text)
                match_dicts = [
                    {
                        "literal": m.literal,
                        "column_ref": m.column_ref,
                        "value": m.value,
                        "score": m.score,
                    }
                    for m in matches
                ]
                events.append(
                    ChatbiQueryStreamEvent(
                        event=CHATBI_SSE_VALUE_FOUNDING,
                        value_founding_literals=literal_dicts,
                        value_founding_matches=match_dicts,
                    )
                )
            search_hits = []
            if ctx.payload.options.value_search_enabled:
                with self._observability.span("ai.chatbi.value_search"):
                    for literal in all_literals:
                        search_hits.extend(
                            await self._value_index.search(
                                datasource_id=datasource_id,
                                literal=literal.value,
                            )
                        )
                search_text = format_value_search_hits_for_text2sql(search_hits)
                if search_text:
                    context_parts.append(search_text)
                events.append(
                    ChatbiQueryStreamEvent(
                        event=CHATBI_SSE_VALUE_SEARCH,
                        value_search_matches=[
                            {
                                "literal": hit.literal,
                                "column_ref": hit.column_ref,
                                "value": hit.value,
                                "score": hit.score,
                                "match_type": hit.match_type,
                                "frequency": hit.frequency,
                            }
                            for hit in search_hits
                        ],
                    )
                )
            self._observability.update_current_trace(
                metadata={
                    "value_founding_literal_count": len(all_literals),
                    "value_founding_match_count": len(matches),
                    "value_search_match_count": len(search_hits),
                }
            )
            return "\n\n".join(context_parts) if context_parts else None, events
        except Exception as exc:
            self._observability.update_current_trace(
                metadata={"value_founding_error": str(exc)},
            )
            return None, []
        finally:
            ctx.meta.value_founding_latency_ms = int((time.perf_counter() - t0) * 1000)

    async def _recall_qsql_and_build_event(
        self,
        *,
        datasource_id: int,
        question: str,
        meta: _RunMeta,
    ) -> tuple[list[dict[str, str]], ChatbiQueryStreamEvent]:
        """召回 Q-SQL 示例，并构造对应 SSE 事件。"""
        t0 = time.perf_counter()
        with self._observability.span("ai.chatbi.qsql_recall"):
            qsql_examples, qsql_hits = await self._recall_qsql(
                datasource_id=datasource_id,
                question=question,
            )
        meta.qsql_recall_latency_ms = int((time.perf_counter() - t0) * 1000)
        return qsql_examples, ChatbiQueryStreamEvent(
            event=CHATBI_SSE_QSQL_RECALL,
            qsql_hits=qsql_hits,
        )

    async def _business_knowledge_for_sql(
        self,
        *,
        datasource_id: int,
        question: str,
        recall_question: str,
        business_knowledge_by_datasource: dict[int, list[dict[str, Any]]],
        meta: _RunMeta,
    ) -> list[dict[str, Any]]:
        """获取 SQL 生成阶段使用的业务知识，澄清改写后会按新问题重召回。"""
        if question.strip() == recall_question.strip():
            return list(business_knowledge_by_datasource.get(datasource_id, []))
        return await self._recall_business_knowledge(
            datasource_id=datasource_id,
            question=question,
            meta=meta,
        )

    async def _generate_sql_with_timing(
        self,
        ctx: _RunContext,
        *,
        ds_record: ChatbiDatasourceRecord,
        schema_selection: _SchemaSelectionResult,
        qsql_examples: list[dict[str, str]],
        business_knowledge: list[dict[str, Any]],
        text2sql_clarification: dict[str, Any],
        rag_knowledge_hits: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ChatbiQueryStreamEvent | None]:
        """调用 Text2SQL 模型并记录本阶段耗时。"""
        clarification_dialogue = build_clarification_dialogue_for_text2sql(
            clarification_question=ctx.state.clarification_question,
            user_clarification_answer=ctx.state.user_clarification_answer,
            clarification_skipped=ctx.state.clarification_skipped,
        )
        t0 = time.perf_counter()
        with self._observability.span("ai.chatbi.text2sql.agentar_scale_sql"):
            text2sql_out, candidate_event = await self._generate_agentar_scaled_sql(
                ctx,
                ds_record=ds_record,
                schema=schema_selection.schema,
                fallback_schema_text=schema_selection.text,
                qsql_examples=qsql_examples,
                business_knowledge=business_knowledge,
                text2sql_clarification=text2sql_clarification,
                clarification_dialogue=clarification_dialogue,
                explicit_paths=ctx.payload.options.sql_candidate_paths,
                rag_knowledge_hits=rag_knowledge_hits,
            )
        ctx.meta.text2sql_latency_ms = int((time.perf_counter() - t0) * 1000)
        return text2sql_out, candidate_event

    async def _generate_agentar_scaled_sql(
        self,
        ctx: _RunContext,
        *,
        ds_record: ChatbiDatasourceRecord,
        schema: ChatbiDbSchemaRecord | None,
        fallback_schema_text: str,
        qsql_examples: list[dict[str, str]],
        business_knowledge: list[dict[str, Any]],
        text2sql_clarification: dict[str, Any],
        clarification_dialogue: str | None,
        explicit_paths: list[str],
        rag_knowledge_hits: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ChatbiQueryStreamEvent]:
        t0 = time.perf_counter()
        if isinstance(schema, ChatbiDbSchemaRecord):
            schema_views = build_agentar_schema_views(schema) or [
                AgentarSchemaView(name="summary", text=fallback_schema_text)
            ]
        else:
            schema_views = [AgentarSchemaView(name="single", text=fallback_schema_text)]
        schema_text_by_name = {view.name: view.text for view in schema_views}
        candidates: list[SqlCandidate] = []
        for schema_view, prompt_format in self._agentar_candidate_paths(
            schema_views,
            paths=explicit_paths,
        ):
            schema_text: str
            if schema_view is not None:
                schema_text = schema_view.text
                schema_format = schema_view.name
            else:
                schema_text = fallback_schema_text
                schema_format = "single"
            candidate = SqlCandidate(
                path_name=f"{schema_format}:{prompt_format}",
                schema_format=schema_format,
                prompt_style=prompt_format,
            )
            try:
                out = await self._generate_sql(
                    question=ctx.state.pipeline_question,
                    db_type=str(ds_record.connector_type or "PostgreSQL"),
                    db_description=schema_text,
                    current_time=ctx.state.current_time,
                    qsql_examples=qsql_examples,
                    business_knowledge=business_knowledge,
                    meta=ctx.meta,
                    clarification_dialogue=clarification_dialogue,
                    prompt_format=prompt_format,
                    value_founding_text=ctx.state.value_founding_text,
                    rag_knowledge_hits=rag_knowledge_hits,
                    **text2sql_clarification,
                )
                candidate.sql = str(out.get("sql") or "").strip() or None
            except Exception as exc:
                candidate.generation_error = str(exc)
            candidates.append(candidate)

        candidates = dedupe_sql_candidates(candidates)
        await self._execute_and_repair_sql_candidates(
            ctx,
            candidates,
            schema_text_by_name=schema_text_by_name,
            fallback_schema_text=fallback_schema_text,
            text2sql_clarification=text2sql_clarification,
        )
        groups = group_sql_candidates(candidates)
        if ctx.payload.options.sql_selection_enabled:
            selected, selection = await self._tournament_select_sql_candidate(
                ctx,
                groups=groups,
                candidates=candidates,
                db_type=str(ds_record.connector_type or "PostgreSQL"),
                schema_text=fallback_schema_text,
                business_knowledge=business_knowledge,
                clarification_dialogue=clarification_dialogue,
            )
        else:
            selected = fallback_select_sql_candidate(
                candidates,
                reason="sql_selection disabled; fallback rank",
            )
            selection = {
                "selection_strategy": "fallback_rank",
                "fallback": "sql_selection_disabled",
            }
        ctx.meta.sql_candidate_latency_ms = int((time.perf_counter() - t0) * 1000)
        if selected is not None:
            ctx.meta.sql_selected_path = selected.path_name
        event = self._build_sql_candidates_event(ctx, candidates, selected, selection)
        if selected is None or not selected.sql:
            return {"success": False, "sql": None}, event
        return {"success": True, "sql": selected.sql}, event

    async def _execute_and_repair_sql_candidates(
        self,
        ctx: _RunContext,
        candidates: list[SqlCandidate],
        *,
        schema_text_by_name: dict[str, str],
        fallback_schema_text: str,
        text2sql_clarification: dict[str, Any],
    ) -> None:
        datasource_id = cast(int, ctx.state.datasource_id)
        for candidate in candidates:
            if not candidate.sql:
                continue
            result = await self._execute_sql_once(
                datasource_id=datasource_id,
                user_id=ctx.payload.user_id,
                sql=candidate.sql,
                max_rows=AGENTAR_CANDIDATE_PROBE_MAX_ROWS,
            )
            if result.error and ctx.payload.options.sql_fix_enabled:
                result = await self._repair_agentar_candidate_sql(
                    ctx,
                    candidate=candidate,
                    datasource_id=datasource_id,
                    schema_text=schema_text_by_name.get(
                        candidate.schema_format,
                        fallback_schema_text,
                    ),
                    error_message=result.error,
                    text2sql_clarification=text2sql_clarification,
                )
            self._apply_candidate_execution_result(candidate, result)

    async def _repair_agentar_candidate_sql(
        self,
        ctx: _RunContext,
        *,
        candidate: SqlCandidate,
        datasource_id: int,
        schema_text: str,
        error_message: str,
        text2sql_clarification: dict[str, Any],
    ) -> _SqlExecutionResult:
        try:
            fixed_sql = await self._fix_sql(
                question=ctx.state.pipeline_question,
                sql=candidate.sql or "",
                schema_text=schema_text,
                error_message=error_message,
                meta=ctx.meta,
                **text2sql_clarification,
            )
        except Exception as exc:
            candidate.execute_error = error_message
            candidate.fix_error = str(exc)
            return _SqlExecutionResult(error=error_message)

        fixed_sql = (fixed_sql or "").strip()
        if not fixed_sql or fixed_sql == candidate.sql:
            candidate.execute_error = error_message
            return _SqlExecutionResult(error=error_message)

        fixed_result = await self._execute_sql_once(
            datasource_id=datasource_id,
            user_id=ctx.payload.user_id,
            sql=fixed_sql,
            max_rows=AGENTAR_CANDIDATE_PROBE_MAX_ROWS,
        )
        if fixed_result.error:
            candidate.execute_error = error_message
            candidate.fix_error = fixed_result.error
            return fixed_result
        candidate.original_sql = candidate.sql
        candidate.sql = fixed_sql
        candidate.fixed = True
        return fixed_result

    @staticmethod
    def _apply_candidate_execution_result(
        candidate: SqlCandidate,
        result: _SqlExecutionResult,
    ) -> None:
        candidate.execute_error = result.error
        if result.error:
            candidate.columns = []
            candidate.rows = []
            candidate.row_count = None
            candidate.truncated = False
            candidate.result_signature = None
            return
        candidate.columns = list(result.columns)
        candidate.rows = json_safe_rows(result.rows)
        candidate.row_count = len(result.rows)
        candidate.truncated = bool(result.truncated)
        candidate.result_signature = ChatbiQueryPipeline._candidate_result_signature(
            columns=candidate.columns,
            rows=candidate.rows,
            truncated=candidate.truncated,
        )

    @staticmethod
    def _candidate_result_signature(
        *,
        columns: list[str],
        rows: list[dict[str, Any]],
        truncated: bool,
    ) -> str:
        return json.dumps(
            {"columns": columns, "rows": rows, "truncated": truncated},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _agentar_candidate_paths(
        schema_views: list[AgentarSchemaView],
        *,
        paths: list[str],
    ) -> list[tuple[AgentarSchemaView | None, str]]:
        by_name = {view.name: view for view in schema_views}
        out: list[tuple[AgentarSchemaView | None, str]] = []
        for path in paths:
            schema_fmt, prompt_fmt = path.split(":", 1)
            if schema_fmt == "single":
                out.append((None, prompt_fmt))
            else:
                view = by_name.get(schema_fmt)
                if view is None:
                    view = schema_views[0]
                out.append((view, prompt_fmt))
        return out

    async def _tournament_select_sql_candidate(
        self,
        ctx: _RunContext,
        *,
        groups: list[SqlCandidateGroup],
        candidates: list[SqlCandidate],
        db_type: str,
        schema_text: str,
        business_knowledge: list[dict[str, Any]],
        clarification_dialogue: str | None,
    ) -> tuple[SqlCandidate | None, dict[str, Any]]:
        if not groups:
            selected = fallback_select_sql_candidate(
                candidates,
                reason="no executable result group; fallback to first usable SQL",
            )
            return selected, {
                "selection_strategy": "tournament_reasoning_selector",
                "fallback": "no_executable_group",
            }
        if len(groups) == 1:
            selected = fallback_select_sql_candidate(
                groups[0].candidates,
                reason="only executable result group",
            )
            if selected is None:
                selected = groups[0].representative
            selected.selected = True
            selected.selection_reason = "only executable result group"
            return selected, {
                "selection_strategy": "tournament_reasoning_selector",
                "fallback": "single_group",
                "group_count": 1,
            }

        consensus = try_consensus_sql_candidate(groups)
        if consensus is not None:
            return consensus, {
                "selection_strategy": "execution_consensus",
                "group_count": len(groups),
            }

        selector_failures = 0
        comparisons: list[dict[str, Any]] = []
        for left_index, left in enumerate(groups):
            for right in groups[left_index + 1 :]:
                try:
                    verdict = await self._judge_agentar_candidate_pair(
                        ctx,
                        db_type=db_type,
                        schema_text=schema_text,
                        business_knowledge=business_knowledge,
                        left=left,
                        right=right,
                        clarification_dialogue=clarification_dialogue,
                    )
                    winner = str(verdict.get("winner") or "tie")
                except Exception as exc:
                    selector_failures += 1
                    winner = self._fallback_pair_winner(left, right)
                    verdict = {
                        "winner": winner,
                        "confidence": 0.0,
                        "reason": f"selector fallback: {exc}",
                    }

                left.comparisons += 1
                right.comparisons += 1
                if winner == "A":
                    left.wins += 1.0
                elif winner == "B":
                    right.wins += 1.0
                else:
                    left.wins += 0.5
                    right.wins += 0.5
                comparisons.append(
                    {
                        "left": left.group_id,
                        "right": right.group_id,
                        "winner": winner,
                        "confidence": verdict.get("confidence"),
                        "reason": verdict.get("reason"),
                    }
                )

        indexed_groups = list(enumerate(groups))
        _, winning_group = max(
            indexed_groups,
            key=lambda item: (
                item[1].wins,
                len(item[1].candidates),
                -item[0],
            ),
        )
        for group in groups:
            for candidate in group.candidates:
                candidate.wins = group.wins
                candidate.comparisons = group.comparisons
                candidate.score = group.wins
                candidate.selected = False
        selected = winning_group.representative
        selected.selected = True
        selected.selection_reason = (
            f"tournament winner: {winning_group.wins:g}/"
            f"{winning_group.comparisons} pairwise points"
        )
        return selected, {
            "selection_strategy": "tournament_reasoning_selector",
            "group_count": len(groups),
            "selected_group_id": winning_group.group_id,
            "selector_failures": selector_failures,
            "comparisons": comparisons,
        }

    async def _judge_agentar_candidate_pair(
        self,
        ctx: _RunContext,
        *,
        db_type: str,
        schema_text: str,
        business_knowledge: list[dict[str, Any]],
        left: SqlCandidateGroup,
        right: SqlCandidateGroup,
        clarification_dialogue: str | None,
    ) -> dict[str, Any]:
        content = await self._llm_completion(
            system=build_agentar_sql_selector_system_prompt(
                db_type=db_type,
                db_description=schema_text,
                current_time=ctx.state.current_time,
            ),
            user=build_agentar_sql_selector_user_content(
                question=ctx.state.pipeline_question,
                business_knowledge=business_knowledge,
                candidate_a=self._selector_candidate_payload(left.representative),
                candidate_b=self._selector_candidate_payload(right.representative),
                clarification_dialogue=clarification_dialogue,
            ),
            meta=ctx.meta,
            temperature=0.0,
        )
        return parse_agentar_sql_selector_response(content)

    @staticmethod
    def _selector_candidate_payload(candidate: SqlCandidate) -> dict[str, Any]:
        row_count = candidate.row_count if candidate.row_count is not None else len(candidate.rows)
        return {
            "path_name": candidate.path_name,
            "schema_format": candidate.schema_format,
            "prompt_format": candidate.prompt_style,
            "group_id": candidate.group_id,
            "group_size": candidate.group_size,
            "sql": candidate.sql,
            "fixed": candidate.fixed,
            "execution": {
                "columns": candidate.columns,
                "column_count": len(candidate.columns or []),
                "rows": candidate.rows[:5],
                "row_count": row_count,
                "is_empty": row_count == 0,
                "truncated": candidate.truncated,
            },
        }

    @staticmethod
    def _fallback_pair_winner(left: SqlCandidateGroup, right: SqlCandidateGroup) -> str:
        left_key = (len(left.candidates), left.representative.fixed)
        right_key = (len(right.candidates), right.representative.fixed)
        if left_key == right_key:
            return "tie"
        return "A" if left_key > right_key else "B"

    @staticmethod
    def _build_sql_candidates_event(
        ctx: _RunContext,
        candidates: list[SqlCandidate],
        selected: SqlCandidate | None,
        selection: dict[str, Any],
    ) -> ChatbiQueryStreamEvent:
        payload_selection = {
            "selected_path": selected.path_name if selected is not None else None,
            "selected_sql": selected.sql if selected is not None else None,
            "reason": selected.selection_reason if selected is not None else None,
            "candidate_count": len(candidates),
        }
        payload_selection.update(selection)
        return ChatbiQueryStreamEvent(
            event=CHATBI_SSE_SQL_CANDIDATES,
            sql_candidates=[candidate.to_stream_dict() for candidate in candidates],
            sql_selection=payload_selection,
        )

    @staticmethod
    def _text2sql_terminal_summary(_text2sql_out: dict[str, Any]) -> str:
        return "无法生成可执行的 SQL，请换个问法或补充业务说明。"

    async def _stream_data_summary_and_persist(
        self,
        ctx: _RunContext,
        *,
        sql: str,
        execution_result: _SqlExecutionResult,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """输出数据、总结和 completed；持久化延后到 completed 之后。"""
        safe_rows = json_safe_rows(execution_result.rows)
        ctx.state.result_preview = {
            "columns": execution_result.columns,
            "rows": safe_rows[:CHATBI_RESULT_PREVIEW_MAX_ROWS],
            "truncated": execution_result.truncated,
            "row_count": len(safe_rows),
        }
        yield ChatbiQueryStreamEvent(
            event=CHATBI_SSE_DATA,
            columns=execution_result.columns,
            rows=safe_rows,
            truncated=execution_result.truncated,
        )

        summary = await self._generate_summary_with_fallback(
            question=ctx.state.pipeline_question,
            sql=ctx.state.final_sql or sql,
            columns=execution_result.columns,
            rows=safe_rows,
            result_truncated=execution_result.truncated,
            meta=ctx.meta,
            summary_enabled=ctx.payload.options.summary_enabled,
        )
        yield ChatbiQueryStreamEvent(event=CHATBI_SSE_SUMMARY, text=summary)

        # completed 必须先发给前端；落库失败只记 trace，不影响本次流式终态。
        self._trace_terminal_outcome(ctx.meta, CHATBI_QUERY_OUTCOME_SUCCESS)
        yield ctx.meta.to_completed_stream_event(session_id=ctx.state.session_id)
        await self._persist_success_after_completed(
            ctx,
            summary=summary,
        )

    async def _prepare_question_context(
        self,
        ctx: _RunContext,
    ) -> ChatbiQueryStreamEvent | None:
        """准备用户问题上下文；澄清续跑不重复改写原问题。"""
        if ctx.payload.clarification_token:
            await self._restore_clarification_context(ctx)
            return None
        return await self._rewrite_question(ctx)

    async def _restore_clarification_context(
        self,
        ctx: _RunContext,
    ) -> None:
        """从澄清 token 恢复上一次意图上下文和会话状态。"""
        payload = ctx.payload
        state = ctx.state
        token = payload.clarification_token
        if token is None:
            raise ChatbiQueryServiceError.bad_request("澄清 token 不能为空")
        state.clarification_skipped = payload.clarification_skip
        state.resume_snapshot = await self._clarification.load(token)
        if state.resume_snapshot is None:
            raise ChatbiQueryServiceError.bad_request("澄清 token 无效或已过期")
        if int(state.resume_snapshot.get("user_id", 0)) != payload.user_id:
            raise ChatbiQueryServiceError.bad_request("澄清 token 与当前用户不匹配")
        snapshot_bound_datasource_id = self._coerce_optional_int(
            state.resume_snapshot.get("bound_datasource_id")
        )
        snapshot_intent = state.resume_snapshot.get("intent_result")
        snapshot_datasource_id = (
            self._coerce_optional_int(snapshot_intent.get("datasource_id"))
            if isinstance(snapshot_intent, dict)
            else None
        )
        state.bound_datasource_id = snapshot_bound_datasource_id or snapshot_datasource_id

        state.user_question = str(state.resume_snapshot.get("user_question") or state.user_question)
        state.snapshot_rewritten_question = str(
            state.resume_snapshot.get("rewritten_question") or state.user_question
        )
        state.rewritten_question = state.snapshot_rewritten_question
        state.clarification_question = (
            str(state.resume_snapshot.get("clarification_question") or "") or None
        )
        raw_options = state.resume_snapshot.get("clarification_options")
        state.clarification_options = list(raw_options) if isinstance(raw_options, list) else []
        state.session_id = self._coerce_optional_int(state.resume_snapshot.get("session_id"))
        state.user_message_id = self._coerce_optional_int(
            state.resume_snapshot.get("user_message_id")
        )
        state.user_clarification_answer = (
            CHATBI_CLARIFICATION_SKIPPED_MARKER
            if state.clarification_skipped
            else payload.question.strip()
        )

        if state.session_id is not None and not state.clarification_skipped:
            state.user_message_id = await self._ensure_user_message(
                session_id=int(state.session_id),
                user_id=payload.user_id,
                content=state.user_clarification_answer,
                request_id=ctx.meta.request_id,
            )
        await self._clarification.delete(token)
        self._observability.update_current_trace(
            metadata={
                "clarification_resume": True,
                "clarification_skip": state.clarification_skipped,
            }
        )

    async def _rewrite_question(
        self,
        ctx: _RunContext,
    ) -> ChatbiQueryStreamEvent:
        """创建用户消息并生成用于后续问数的改写问题。"""
        payload = ctx.payload
        state = ctx.state
        meta = ctx.meta
        if state.session_id is not None:
            state.user_message_id = await self._ensure_user_message(
                session_id=state.session_id,
                user_id=payload.user_id,
                content=state.user_question,
                request_id=meta.request_id,
            )
        history = await self._load_rewrite_history(state.session_id, payload.user_id)
        if not payload.options.rewrite_enabled:
            state.rewritten_question = state.user_question
            state.snapshot_rewritten_question = state.rewritten_question
            meta.rewrite_latency_ms = 0
            return ChatbiQueryStreamEvent(
                event=CHATBI_SSE_REWRITTEN_QUESTION,
                question=state.rewritten_question,
                is_degraded=False,
            )
        t0 = time.perf_counter()
        with self._observability.span(
            "ai.chatbi.rewrite",
            metadata={"request_id": meta.request_id},
        ):
            rewrite_out = await self._rewrite.rewrite(
                RewriteInput(
                    original_question=state.user_question,
                    recent_messages=history,
                    request_id=meta.request_id,
                    user_id=str(payload.user_id),
                ),
                strategy=RewriteStrategyType.LLM,
            )
        meta.rewrite_latency_ms = int((time.perf_counter() - t0) * 1000)
        meta.is_degraded_rewrite = rewrite_out.is_degraded
        meta.add_usage_tokens(
            prompt_tokens=cast(int | None, rewrite_out.metadata.get("prompt_tokens")),
            completion_tokens=cast(int | None, rewrite_out.metadata.get("completion_tokens")),
        )
        state.rewritten_question = rewrite_out.rewritten_question
        state.snapshot_rewritten_question = state.rewritten_question
        return ChatbiQueryStreamEvent(
            event=CHATBI_SSE_REWRITTEN_QUESTION,
            question=state.rewritten_question,
            is_degraded=rewrite_out.is_degraded,
        )

    async def _prepare_datasource_candidates(
        self,
        ctx: _RunContext,
    ) -> list[dict[str, Any]]:
        """准备意图识别可见的数据源列表，澄清跳过时收窄到快照数据源。"""
        payload = ctx.payload
        state = ctx.state
        if state.bound_datasource_id is not None:
            bound_record = await self._ds_repo.get_for_user(
                state.bound_datasource_id,
                payload.user_id,
            )
            if bound_record is None:
                raise ChatbiQueryServiceError.not_found("数据源不存在或无权访问")
            if not bound_record.db_schema:
                state.candidate_datasources = []
                return []
            bound_info = self._datasource_info_from_record(bound_record)
            state.candidate_datasources = [bound_info]
            return [bound_info]

        available_datasources = await self._list_ready_datasources(payload.user_id)
        state.candidate_datasources = self._datasources_for_intent(
            available_datasources,
            state.bound_datasource_id,
        )
        if payload.clarification_token and state.resume_snapshot:
            snap_intent = state.resume_snapshot.get("intent_result")
            if isinstance(snap_intent, dict):
                snap_ds_id = self._coerce_optional_int(snap_intent.get("datasource_id"))
                if snap_ds_id is not None:
                    narrowed = [
                        ds for ds in state.candidate_datasources if int(ds["id"]) == snap_ds_id
                    ]
                    if narrowed:
                        state.candidate_datasources = narrowed
        return available_datasources

    async def _resolve_intent(
        self,
        ctx: _RunContext,
        *,
        business_knowledge: list[dict[str, Any]],
    ) -> None:
        """识别或恢复问数意图，并处理澄清提交后的选源收敛。"""
        payload = ctx.payload
        state = ctx.state
        meta = ctx.meta
        if payload.clarification_token and state.clarification_skipped:
            raw_intent = state.resume_snapshot.get("intent_result") if state.resume_snapshot else {}
            state.intent_result = dict(raw_intent) if isinstance(raw_intent, dict) else {}
            state.intent_value = ChatbiQueryIntent.QUERY.value
            raw_detail = (state.resume_snapshot or {}).get("intent_detail")
            state.intent_detail = (
                dict(raw_detail)
                if isinstance(raw_detail, dict)
                else intent_detail_from_result(state.intent_result)
            )
        elif not payload.options.intent_enabled:
            self._apply_skipped_intent(ctx)
        else:
            t0 = time.perf_counter()
            with self._observability.span("ai.chatbi.intent"):
                state.intent_result = await self._run_intent(
                    question=state.user_question,
                    rewritten_question=state.snapshot_rewritten_question,
                    current_time=state.current_time,
                    available_datasources=state.candidate_datasources,
                    business_knowledge=business_knowledge,
                    is_clarification_resume=bool(payload.clarification_token),
                    clarification_question=state.clarification_question,
                    clarification_options=state.clarification_options,
                    user_clarification_answer=state.user_clarification_answer,
                    meta=meta,
                )
            meta.intent_latency_ms = int((time.perf_counter() - t0) * 1000)
            state.intent_value = str(
                state.intent_result.get("intent", ChatbiQueryIntent.QUERY.value)
            )
            state.intent_detail = intent_detail_from_result(state.intent_result)

        self._promote_clarification_to_query_if_resolved(ctx)
        self._promote_clarification_to_query_if_disabled(ctx)

    @staticmethod
    def _apply_skipped_intent(ctx: _RunContext) -> None:
        """自动化问数（如 benchmark）跳过 intent LLM，直接按绑定/候选数据源继续。"""
        state = ctx.state
        ds_id = ChatbiQueryPipeline._resolve_datasource_from_intent(
            {},
            state.candidate_datasources,
            state.bound_datasource_id,
        )
        state.intent_value = ChatbiQueryIntent.QUERY.value
        state.intent_result = {
            "intent": ChatbiQueryIntent.QUERY.value,
            "choice": ChatbiQueryIntent.QUERY.value,
            "datasource_id": ds_id,
            "brief_explanation": "意图识别已跳过",
        }
        state.intent_detail = intent_detail_from_result(state.intent_result)

    def _promote_clarification_to_query_if_disabled(
        self,
        ctx: _RunContext,
    ) -> None:
        """自动化问数（如 benchmark）禁用澄清时，在数据源已绑定时直接继续 SQL 生成。"""
        if ctx.payload.options.clarification_enabled:
            return
        state = ctx.state
        if state.intent_value != ChatbiQueryIntent.CLARIFICATION.value:
            return
        resolved_ds = self._resolve_datasource_from_intent(
            state.intent_result,
            state.candidate_datasources,
            state.bound_datasource_id,
        )
        if resolved_ds is None:
            return
        state.intent_value = ChatbiQueryIntent.QUERY.value
        state.intent_result = {
            **state.intent_result,
            "intent": ChatbiQueryIntent.QUERY.value,
            "datasource_id": resolved_ds,
        }
        state.intent_detail = intent_detail_from_result(state.intent_result)

    def _promote_clarification_to_query_if_resolved(
        self,
        ctx: _RunContext,
    ) -> None:
        """澄清提交后如果已能确定数据源，就继续原问数链路。"""
        payload = ctx.payload
        state = ctx.state
        if (
            state.intent_value != ChatbiQueryIntent.CLARIFICATION.value
            or not payload.clarification_token
            or state.clarification_skipped
            or not state.user_clarification_answer
        ):
            return
        resolved_ds = self._resolve_datasource_from_intent(
            state.intent_result,
            state.candidate_datasources,
            state.bound_datasource_id,
        )
        if resolved_ds is None:
            return
        state.intent_value = ChatbiQueryIntent.QUERY.value
        state.intent_result = {
            **state.intent_result,
            "intent": ChatbiQueryIntent.QUERY.value,
            "datasource_id": resolved_ds,
        }
        state.intent_detail = intent_detail_from_result(state.intent_result)

    async def _save_clarification_request(
        self,
        ctx: _RunContext,
    ) -> str:
        """保存澄清快照，供下一次携带 token 续跑。"""
        token = ChatbiClarificationStore.generate_token()
        await self._clarification.save(
            token=token,
            payload={
                "user_id": ctx.payload.user_id,
                "session_id": ctx.state.session_id,
                "user_message_id": ctx.state.user_message_id,
                "request_id": ctx.meta.request_id,
                "user_question": ctx.state.user_question,
                "rewritten_question": ctx.state.snapshot_rewritten_question,
                "bound_datasource_id": ctx.state.bound_datasource_id,
                "clarification_question": str(
                    ctx.state.intent_result.get("clarification_question", "")
                ),
                "clarification_options": list(ctx.state.intent_result.get("options") or []),
                "intent_result": ctx.state.intent_result,
                "intent_value": ctx.state.intent_value,
                "intent_detail": ctx.state.intent_detail,
            },
        )
        return token

    @staticmethod
    def _set_pipeline_question(ctx: _RunContext) -> None:
        """生成下游 SQL 链路实际使用的问题文本。"""
        payload = ctx.payload
        state = ctx.state
        if not payload.clarification_token:
            state.pipeline_question = state.rewritten_question
            return
        if state.clarification_skipped:
            state.pipeline_question = state.snapshot_rewritten_question
            return
        state.pipeline_question = build_effective_question_after_clarification(
            rewritten_question=state.snapshot_rewritten_question,
            clarification_question=state.clarification_question,
            user_clarification_answer=state.user_clarification_answer,
        )

    async def _validate_sql_after_generation(
        self,
        ctx: _RunContext,
        *,
        ds_record: ChatbiDatasourceRecord,
        sql: str,
        schema: ChatbiDbSchemaRecord,
        schema_text: str,
        text2sql_clarification: dict[str, Any],
    ) -> SqlValidateResult:
        """Validate generated SQL with schema evidence, execution preview, and LLM review."""
        datasource_id = cast(int, ctx.state.datasource_id)
        original_sql = sql
        t0 = time.perf_counter()
        with self._observability.span("ai.chatbi.sql_validate"):
            probe_result = await self._execute_sql_once(
                datasource_id=datasource_id,
                user_id=ctx.payload.user_id,
                sql=sql,
                max_rows=CHATBI_RESULT_PREVIEW_MAX_ROWS,
            )
            execution = SqlValidateExecution(
                success=probe_result.error is None,
                columns=probe_result.columns,
                rows=probe_result.rows,
                truncated=probe_result.truncated,
                error=probe_result.error,
            )
            validate_context = build_sql_validate_context(
                sql=sql,
                schema=schema,
                connector_type=str(ds_record.connector_type or ""),
                execution=execution,
            )
            content = await self._llm_completion(
                system=SQL_VALIDATE_SYSTEM,
                user=build_sql_validate_user_content(
                    question=ctx.state.pipeline_question,
                    sql=sql,
                    schema_text=schema_text,
                    validate_context=validate_context.as_dict(),
                    **text2sql_clarification,
                ),
                meta=ctx.meta,
                temperature=0.1,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        ctx.meta.sql_validate_latency_ms = latency_ms
        try:
            parsed = parse_text2sql_response(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ChatbiQueryServiceError.system_error("SQL validate 结果解析失败") from exc
        validated_sql = str(parsed.get("sql") or "").strip() or original_sql
        return SqlValidateResult(
            original_sql=original_sql,
            validated_sql=validated_sql,
            changed=validated_sql != original_sql,
            latency_ms=latency_ms,
            context=validate_context.as_dict(),
        )

    async def _run_group_by_audit(
        self,
        ctx: _RunContext,
        *,
        sql: str,
        ds_record: ChatbiDatasourceRecord,
        schema_text: str,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """Run GROUP BY audit agent, yielding per-round SSE events."""
        datasource_id = cast(int, ctx.state.datasource_id)

        async def _execute_probe(probe_sql: str, max_rows: int = 30) -> tuple[list[str], list[dict[str, Any]], bool]:
            result = await self._execute_sql_once(
                datasource_id=datasource_id,
                user_id=ctx.payload.user_id,
                sql=probe_sql,
                max_rows=max_rows,
            )
            if result.error:
                raise RuntimeError(result.error)
            return result.columns, result.rows, result.truncated

        auditor = GroupByAuditorRunner(
            llm_service=self._llm,
            execute_sql=_execute_probe,
            max_rounds=6,
            timeout=90,
        )
        db_type = str(ds_record.connector_type or "SQLITE").upper()
        t0 = time.perf_counter()
        with self._observability.span("ai.chatbi.group_by_audit"):
            try:
                async for event in auditor.run_stream(
                    sql=sql,
                    question=ctx.state.pipeline_question,
                    db_type=db_type,
                    schema_text=schema_text,
                    model=ctx.payload.options.completion_model,
                ):
                    event_type = event.get("type")
                    if event_type == "thinking":
                        yield ChatbiQueryStreamEvent(
                            event=CHATBI_SSE_SQL_GROUP_AUDIT,
                            group_audit={
                                "phase": "thinking",
                                "agent": event.get("agent"),
                                "round": event.get("round"),
                                "thought": event.get("thought"),
                                "issues": event.get("issues"),
                                "final_sql": event.get("final_sql"),
                            },
                        )
                    elif event_type == "tool_call":
                        yield ChatbiQueryStreamEvent(
                            event=CHATBI_SSE_SQL_GROUP_AUDIT,
                            group_audit={
                                "phase": "tool_call",
                                "agent": event.get("agent"),
                                "round": event.get("round"),
                                "tool": event.get("tool"),
                                "params": event.get("params"),
                            },
                        )
                    elif event_type == "tool_result":
                        yield ChatbiQueryStreamEvent(
                            event=CHATBI_SSE_SQL_GROUP_AUDIT,
                            group_audit={
                                "phase": "tool_result",
                                "agent": event.get("agent"),
                                "round": event.get("round"),
                                "tool": event.get("tool"),
                                "result": event.get("result"),
                            },
                        )
                    elif event_type == "final":
                        yield ChatbiQueryStreamEvent(
                            event=CHATBI_SSE_SQL_GROUP_AUDIT,
                            group_audit={
                                "phase": "final",
                                "agent": event.get("agent"),
                                "thought": event.get("thought"),
                                "issues": event.get("issues"),
                                "sql": event.get("sql"),
                            },
                        )
            except Exception:
                pass
        latency_ms = int((time.perf_counter() - t0) * 1000)
        ctx.meta.sql_validate_latency_ms = (
            (ctx.meta.sql_validate_latency_ms or 0) + latency_ms
        )

    async def _execute_sql_with_optional_fix(
        self,
        ctx: _RunContext,
        *,
        sql: str,
        schema_text: str,
        text2sql_clarification: dict[str, Any],
    ) -> tuple[_SqlExecutionResult, str | None]:
        """执行 SQL；首次失败时按既有规则只尝试一次修复。"""
        datasource_id = cast(int, ctx.state.datasource_id)
        t0 = time.perf_counter()
        with self._observability.span("ai.chatbi.execute"):
            result = await self._execute_sql_once(
                datasource_id=datasource_id,
                user_id=ctx.payload.user_id,
                sql=sql,
            )
        ctx.meta.execute_latency_ms = int((time.perf_counter() - t0) * 1000)

        if (
            result.error is None
            or not ctx.payload.options.sql_fix_enabled
            or ctx.meta.sql_fix_attempts >= self._sql_fix_max_attempts(ctx)
        ):
            return result, None

        ctx.meta.sql_fix_attempts += 1
        with self._observability.span("ai.chatbi.sql_fix"):
            fixed_sql = await self._fix_sql(
                question=ctx.state.pipeline_question,
                sql=sql,
                schema_text=schema_text,
                error_message=result.error,
                meta=ctx.meta,
                **text2sql_clarification,
            )
        if not fixed_sql or fixed_sql == sql:
            return result, None

        # 修复 SQL 仍沿用原终态事件格式；失败时只返回最终 SQL 和失败事件。
        fixed_result = await self._execute_sql_once(
            datasource_id=datasource_id,
            user_id=ctx.payload.user_id,
            sql=fixed_sql,
        )
        if fixed_result.error is None:
            ctx.meta.sql_fix_applied = True
        return fixed_result, fixed_sql

    async def _execute_sql_once(
        self,
        *,
        datasource_id: int,
        user_id: int,
        sql: str,
        max_rows: int | None = None,
    ) -> _SqlExecutionResult:
        try:
            kwargs: dict[str, Any] = {}
            if max_rows is not None:
                kwargs["max_rows"] = max_rows
            columns, rows, truncated = await self._sql_executor.execute(
                datasource_id=datasource_id,
                user_id=user_id,
                sql=sql,
                **kwargs,
            )
        except ChatbiDatasourceServiceError as exc:
            if exc.code in {ErrorCode.PARAMS_INVALID, ErrorCode.CONNECTION_FAILED}:
                return _SqlExecutionResult(error=exc.message)
            if exc.code == ErrorCode.NOT_FOUND:
                raise ChatbiQueryServiceError.not_found(exc.message) from exc
            raise ChatbiQueryServiceError.system_error("SQL 执行服务异常") from exc
        return _SqlExecutionResult(columns=columns, rows=rows, truncated=truncated)

    async def _generate_summary_with_fallback(
        self,
        *,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        result_truncated: bool,
        meta: _RunMeta,
        summary_enabled: bool = True,
    ) -> str:
        """生成结果总结；总结失败不影响已完成的数据查询。"""
        t0 = time.perf_counter()
        if not summary_enabled:
            meta.summary_latency_ms = int((time.perf_counter() - t0) * 1000)
            return "查询已完成。"
        with self._observability.span("ai.chatbi.summary"):
            try:
                summary = await self._generate_summary(
                    question=question,
                    sql=sql,
                    columns=columns,
                    rows=rows,
                    result_truncated=result_truncated,
                    meta=meta,
                )
            except Exception as exc:
                self._observability.update_current_trace(
                    metadata={"summary_error": str(exc)},
                )
                summary = "查询已完成，结果见上方数据。"
        meta.summary_latency_ms = int((time.perf_counter() - t0) * 1000)
        return summary

    async def _stream_terminal_summary_for_state(
        self,
        ctx: _RunContext,
        *,
        summary: str,
        outcome: str | None,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """按固定终态顺序输出 summary/completed，并复用当前运行状态持久化。"""
        async for event in self._stream_terminal_summary(
            summary=summary,
            payload=ctx.payload,
            session_id=ctx.state.session_id,
            user_message_id=ctx.state.user_message_id,
            user_question=ctx.state.user_question,
            rewritten_question=ctx.state.rewritten_question,
            datasource_id=ctx.state.datasource_id,
            meta=ctx.meta,
            intent=ctx.state.intent_value,
            intent_detail=ctx.state.intent_detail,
            outcome=outcome,
        ):
            yield event

    async def _persist_success_after_completed(
        self,
        ctx: _RunContext,
        *,
        summary: str,
    ) -> None:
        """completed 已输出后再持久化，避免落库异常影响前端终态。"""
        if ctx.state.session_id is None:
            return
        try:
            await self._persist_success(
                payload=ctx.payload,
                session_id=int(ctx.state.session_id),
                user_message_id=self._coerce_optional_int(ctx.state.user_message_id),
                user_question=ctx.state.user_question,
                rewritten_question=ctx.state.pipeline_question,
                datasource_id=ctx.state.datasource_id,
                intent=ctx.state.intent_value,
                final_sql=ctx.state.final_sql,
                result_preview=ctx.state.result_preview,
                summary=summary,
                meta=ctx.meta,
            )
        except Exception as exc:
            self._query_persistence.trace_persist_error(exc)

    async def _stream_failed_and_persist(
        self,
        ctx: _RunContext,
        *,
        message: str,
        detail: str,
        outcome: str,
        rewritten_question: str | None = None,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """按固定失败事件顺序输出，并写入失败记录。"""
        yield _failed_stream_event(
            message,
            detail,
            request_id=ctx.meta.request_id,
            session_id=ctx.state.session_id,
        )
        self._trace_terminal_outcome(
            ctx.meta,
            outcome,
            error=message,
            error_detail=detail,
        )
        yield ctx.meta.to_completed_stream_event(session_id=ctx.state.session_id)
        await self._persist_failure(
            payload=ctx.payload,
            session_id=ctx.state.session_id,
            user_message_id=ctx.state.user_message_id,
            user_question=ctx.state.user_question,
            rewritten_question=rewritten_question or ctx.state.rewritten_question,
            datasource_id=ctx.state.datasource_id,
            intent=ctx.state.intent_value,
            final_sql=ctx.state.final_sql,
            meta=ctx.meta,
            message=message,
            detail=detail,
            outcome=outcome,
        )

    async def _llm_completion(
        self,
        *,
        system: str,
        user: str,
        meta: _RunMeta,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> str:
        response: CompletionResponse | None = None
        for attempt in range(2):
            try:
                response = cast(
                    CompletionResponse,
                    await self._llm.acompletion(
                        CompletionRequest(
                            messages=[
                                Message(role=CHAT_MESSAGE_ROLE_SYSTEM, content=system),
                                Message(role=CHAT_MESSAGE_ROLE_USER, content=user),
                            ],
                            temperature=temperature,
                            model=model or self._active_completion_model,
                        )
                    ),
                )
                break
            except Exception:
                if attempt >= 1:
                    raise
                await asyncio.sleep(5)
        if response is None:
            raise ChatbiQueryServiceError.system_error("模型返回为空")
        meta.add_usage(response)
        if not response.choices:
            raise ChatbiQueryServiceError.system_error("模型返回为空")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ChatbiQueryServiceError.system_error("模型返回空内容")
        return content.strip()

    async def _ensure_user_message(
        self,
        *,
        session_id: int,
        user_id: int,
        content: str,
        request_id: str,
    ) -> int:
        return await self._query_persistence.ensure_user_message(
            session_id=session_id,
            user_id=user_id,
            content=content,
            request_id=request_id,
        )

    async def _load_rewrite_history(
        self,
        session_id: int | None,
        user_id: int,
    ) -> list[RewriteMessage]:
        if session_id is None:
            return []
        messages = await self._chat_repo.list_recent_success_messages(
            session_id=session_id,
            limit=CHATBI_QUERY_HISTORY_LIMIT,
        )
        history: list[RewriteMessage] = []
        for msg in messages:
            role = str(msg.role).lower()
            if role not in {CHAT_MESSAGE_ROLE_USER, CHAT_MESSAGE_ROLE_ASSISTANT}:
                continue
            history.append(RewriteMessage(role=role, content=str(msg.content or "")))
        return history

    async def _list_ready_datasources(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self._ds_repo.list_ready_for_user(
            user_id=user_id,
            limit=CHATBI_QUERY_DATASOURCE_CANDIDATE_LIMIT,
        )
        return [self._datasource_info_from_record(row) for row in rows]

    @staticmethod
    def _datasource_info_from_record(record: ChatbiDatasourceRecord) -> dict[str, Any]:
        """从数据源记录构造意图/选源共用的信息字典。"""
        return {
            "id": int(record.id),
            "name": str(record.name),
            "description": datasource_description_from_db_schema(record.db_schema),
            "table_names": table_names_from_db_schema(record.db_schema),
        }

    @staticmethod
    def _coerce_optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _datasources_for_intent(
        available_datasources: list[dict[str, Any]],
        bound_datasource_id: int | None,
    ) -> list[dict[str, Any]]:
        """绑定数据源时，意图识别提示词仅展示该数据源。"""
        if bound_datasource_id is None:
            return available_datasources
        return [ds for ds in available_datasources if int(ds["id"]) == int(bound_datasource_id)]

    @staticmethod
    def _resolve_datasource_from_intent(
        intent_result: dict[str, Any],
        candidate_datasources: list[dict[str, Any]],
        bound_datasource_id: int | None,
    ) -> int | None:
        if bound_datasource_id is not None:
            return int(bound_datasource_id)
        if not candidate_datasources:
            return None

        valid_ids = {int(ds["id"]) for ds in candidate_datasources}
        ds_id = intent_result.get("datasource_id")
        if ds_id is None:
            return None
        try:
            resolved = int(ds_id)
        except (TypeError, ValueError):
            return None
        return resolved if resolved in valid_ids else None

    async def _recall_business_knowledge_for_candidates(
        self,
        *,
        candidate_datasources: list[dict[str, Any]],
        question: str,
        meta: _RunMeta,
    ) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
        del meta
        merged: list[dict[str, Any]] = []
        by_datasource: dict[int, list[dict[str, Any]]] = {}
        seen: set[int] = set()
        embedding = await self._build_business_knowledge_embedding(question)
        if not embedding:
            return merged, by_datasource
        for ds in candidate_datasources:
            ds_id = int(ds["id"])
            hits = await self._biz_kn.search_business_knowledge_by_datasource(
                datasource_id=ds_id,
                embedding=embedding,
                top_k=CHATBI_BUSINESS_KNOWLEDGE_TOP_K,
            )
            by_datasource[ds_id] = hits
            for item in hits:
                rid = int(item.get("business_knowledge_id") or 0)
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                merged.append(item)
        return merged, by_datasource

    async def _recall_business_knowledge(
        self,
        *,
        datasource_id: int,
        question: str,
        meta: _RunMeta,
    ) -> list[dict[str, Any]]:
        del meta
        embedding = await self._build_business_knowledge_embedding(question)
        if not embedding:
            return []
        return await self._biz_kn.search_business_knowledge_by_datasource(
            datasource_id=datasource_id,
            embedding=embedding,
            top_k=CHATBI_BUSINESS_KNOWLEDGE_TOP_K,
        )

    async def _build_business_knowledge_embedding(self, question: str) -> list[float] | None:
        emb = await self._llm.aembedding(EmbeddingRequest(input_texts=[question]))
        if not emb.embeddings:
            return None
        return emb.embeddings[0]

    async def _run_intent(
        self,
        *,
        question: str,
        rewritten_question: str,
        current_time: str,
        available_datasources: list[dict[str, Any]],
        business_knowledge: list[dict[str, Any]],
        is_clarification_resume: bool,
        clarification_question: str | None = None,
        clarification_options: list[str] | None = None,
        user_clarification_answer: str | None = None,
        meta: _RunMeta,
    ) -> dict[str, Any]:
        content = await self._llm_completion(
            system=INTENT_SYSTEM,
            user=build_intent_user_content(
                question=question,
                rewritten_question=rewritten_question,
                current_time=current_time,
                datasource_list=available_datasources,
                business_knowledge=business_knowledge,
                is_clarification_resume=is_clarification_resume,
                clarification_question=clarification_question,
                clarification_options=clarification_options,
                user_clarification_answer=user_clarification_answer,
            ),
            meta=meta,
        )
        try:
            return parse_intent_response(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ChatbiQueryServiceError.system_error("意图识别解析失败") from exc

    async def _recall_qsql(
        self,
        *,
        datasource_id: int,
        question: str,
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        emb = await self._llm.aembedding(EmbeddingRequest(input_texts=[question]))
        if not emb.embeddings:
            return [], []
        scope_filter = await self._resolve_global_qsql_scope_filter(datasource_id)
        candidate_top_k = CHATBI_QSQL_RECALL_CANDIDATE_TOP_N
        if scope_filter is not None:
            candidate_top_k = max(
                candidate_top_k,
                CHATBI_QSQL_RECALL_FILTERED_CANDIDATE_TOP_N,
            )
        hits = await self._vector_store.search_qsql_pool(
            datasource_ids=[datasource_id, QSQL_GLOBAL_DATASOURCE_ID],
            embedding=emb.embeddings[0],
            top_k=max(candidate_top_k, CHATBI_QSQL_RECALL_TOP_N),
        )
        candidates: list[QsqlRetrievalCandidate] = []
        seen_qsql_ids: set[int] = set()
        for hit in hits:
            if int(hit.qsql_id) in seen_qsql_ids:
                continue
            seen_qsql_ids.add(int(hit.qsql_id))
            row = await self._qsql_repo.get_by_id(hit.qsql_id)
            if row is None:
                continue
            scope = row.scope or QSQL_SCOPE_DATASOURCE
            if scope == QSQL_SCOPE_DATASOURCE and int(row.datasource_id) != datasource_id:
                continue
            if scope == QSQL_SCOPE_GLOBAL and int(row.datasource_id) != QSQL_GLOBAL_DATASOURCE_ID:
                continue
            if not global_qsql_matches_scope(row, scope_filter=scope_filter):
                continue
            candidates.append(QsqlRetrievalCandidate(record=row, vector_score=float(hit.score)))

        ranked = rank_qsql_candidates(
            question=question,
            candidates=candidates,
            top_k=CHATBI_QSQL_RECALL_TOP_N,
        )
        examples: list[dict[str, str]] = []
        recalled: list[dict[str, Any]] = []
        for item in ranked:
            row = item.record
            examples.append({"question": row.question, "sql_body": row.sql_body})
            recalled.append(
                {
                    "qsql_id": int(row.id),
                    "score": float(item.score),
                    "vector_score": float(item.vector_score),
                    "lexical_score": float(item.lexical_score),
                    "skeleton_score": float(item.skeleton_score),
                    "question": row.question,
                    "sql_body": row.sql_body,
                    "scope": row.scope,
                    "source_dataset": row.source_dataset,
                    "source_db_id": row.source_db_id,
                    "retrieval_strategy": "DAIL_SQL_HYBRID",
                }
            )
        return examples, recalled

    async def _resolve_global_qsql_scope_filter(
        self,
        datasource_id: int,
    ) -> GlobalQsqlScopeFilter | None:
        scope = await self._benchmark_repo.get_datasource_qsql_scope_filter(datasource_id)
        if scope is None:
            return None
        source_dataset, source_db_id = scope
        return GlobalQsqlScopeFilter(
            source_dataset=source_dataset,
            source_db_id=source_db_id,
        )

    async def _generate_sql(
        self,
        *,
        question: str,
        db_type: str,
        db_description: str,
        current_time: str,
        qsql_examples: list[dict[str, str]],
        business_knowledge: list[dict[str, Any]],
        meta: _RunMeta,
        clarification_question: str | None = None,
        user_clarification_answer: str | None = None,
        clarification_dialogue: str | None = None,
        prompt_format: str = "direct",
        value_founding_text: str | None = None,
        rag_knowledge_hits: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        content = await self._llm_completion(
            system=build_text2sql_system_prompt(
                db_type=db_type,
                db_description=db_description,
                current_time=current_time,
                prompt_format=prompt_format,
            ),
            user=build_text2sql_user_content(
                question=question,
                qsql_examples=qsql_examples,
                business_knowledge=business_knowledge,
                clarification_question=clarification_question,
                user_clarification_answer=user_clarification_answer,
                clarification_dialogue=clarification_dialogue,
                value_founding_text=value_founding_text,
                rag_knowledge_hits=rag_knowledge_hits,
            ),
            meta=meta,
        )
        try:
            return parse_text2sql_response(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ChatbiQueryServiceError.system_error("SQL 生成结果解析失败") from exc

    async def _fix_sql(
        self,
        *,
        question: str,
        sql: str,
        schema_text: str,
        error_message: str,
        meta: _RunMeta,
        clarification_question: str | None = None,
        user_clarification_answer: str | None = None,
    ) -> str:
        content = await self._llm_completion(
            system=SQL_FIX_ERROR_SYSTEM,
            user=build_sql_fix_user_content(
                question=question,
                sql=sql,
                error_message=error_message,
                schema_text=schema_text,
                clarification_question=clarification_question,
                user_clarification_answer=user_clarification_answer,
            ),
            meta=meta,
        )
        return extract_sql_from_llm(content)

    async def _generate_summary(
        self,
        *,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        result_truncated: bool,
        meta: _RunMeta,
    ) -> str:
        row_count = len(rows)
        preview_row_count = min(row_count, CHATBI_SUMMARY_PREVIEW_MAX_ROWS)
        user = build_summary_user_content(
            question=question,
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=row_count,
            preview_row_count=preview_row_count,
            result_truncated=result_truncated,
            preview_max_rows=CHATBI_SUMMARY_PREVIEW_MAX_ROWS,
        )
        return await self._llm_completion(
            system=SUMMARY_SYSTEM,
            user=user,
            meta=meta,
            temperature=0.3,
        )

    async def _stream_terminal_summary(
        self,
        *,
        summary: str,
        payload: ChatbiQueryRunInput,
        session_id: int | None,
        user_message_id: int | None,
        user_question: str,
        rewritten_question: str,
        meta: _RunMeta,
        datasource_id: int | None = None,
        intent: str | None = None,
        intent_detail: dict[str, Any] | None = None,
        outcome: str | None = None,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        """以固定 summary 结束问数，并写入会话与 query_log（若有 session）。"""
        yield ChatbiQueryStreamEvent(event=CHATBI_SSE_SUMMARY, text=summary)
        self._trace_terminal_outcome(meta, outcome)
        yield meta.to_completed_stream_event(session_id=session_id)
        if session_id is not None:
            log_meta = meta.to_dict()
            if outcome:
                log_meta["outcome"] = outcome
            try:
                await self._persist_success(
                    payload=payload,
                    session_id=int(session_id),
                    user_message_id=self._coerce_optional_int(user_message_id),
                    user_question=user_question,
                    rewritten_question=rewritten_question,
                    datasource_id=datasource_id,
                    intent=intent,
                    final_sql=None,
                    result_preview=None,
                    summary=summary,
                    meta=meta,
                    log_meta=log_meta,
                )
            except Exception as exc:
                self._query_persistence.trace_persist_error(exc)

    async def _persist_success(
        self,
        *,
        payload: ChatbiQueryRunInput,
        session_id: int,
        user_message_id: int | None,
        user_question: str,
        rewritten_question: str,
        datasource_id: int | None,
        intent: str | None,
        final_sql: str | None,
        result_preview: dict[str, Any] | None,
        summary: str,
        meta: _RunMeta,
        log_meta: dict[str, Any] | None = None,
        status: str = CHAT_MESSAGE_STATUS_SUCCESS,
        error: dict[str, Any] | None = None,
    ) -> None:
        await self._query_persistence.persist_success(
            payload=payload,
            session_id=session_id,
            user_message_id=user_message_id,
            user_question=user_question,
            rewritten_question=rewritten_question,
            datasource_id=datasource_id,
            intent=intent,
            final_sql=final_sql,
            result_preview=result_preview,
            summary=summary,
            meta=meta,
            log_meta=log_meta,
            status=status,
            error=error,
        )

    async def _persist_failure(
        self,
        *,
        payload: ChatbiQueryRunInput,
        session_id: int | None,
        user_message_id: int | None,
        user_question: str,
        rewritten_question: str,
        datasource_id: int | None,
        intent: str | None,
        final_sql: str | None,
        meta: _RunMeta,
        message: str,
        detail: str,
        outcome: str,
    ) -> None:
        if session_id is None:
            return
        log_meta = meta.to_dict()
        log_meta["outcome"] = outcome
        log_meta["error"] = message
        if detail:
            log_meta["error_detail"] = detail
        try:
            await self._persist_success(
                payload=payload,
                session_id=int(session_id),
                user_message_id=self._coerce_optional_int(user_message_id),
                user_question=user_question,
                rewritten_question=rewritten_question,
                datasource_id=datasource_id,
                intent=intent,
                final_sql=final_sql,
                result_preview=None,
                summary=message,
                meta=meta,
                log_meta=log_meta,
                status=CHAT_MESSAGE_STATUS_FAILED,
                error={"message": message},
            )
        except Exception as exc:
            self._query_persistence.trace_persist_error(exc)

    def _trace_terminal_outcome(
        self,
        meta: _RunMeta,
        outcome: str | None,
        *,
        error: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        """问数结束前统一回填终态，保证所有收束路径都能排查。"""
        trace_meta = meta.to_dict()
        if outcome:
            trace_meta["outcome"] = outcome
        if error:
            trace_meta["error"] = error
        if error_detail:
            trace_meta["error_detail"] = error_detail
        self._observability.update_current_trace(metadata=trace_meta)


def _failed_stream_event(
    message: str,
    detail: str,
    *,
    request_id: str | None,
    session_id: int | None,
) -> ChatbiQueryStreamEvent:
    del detail
    return ChatbiQueryStreamEvent(
        event=CHATBI_SSE_FAILED,
        request_id=request_id,
        session_id=session_id,
        error={"message": message},
    )


__all__ = ["ChatbiQueryPipeline"]




