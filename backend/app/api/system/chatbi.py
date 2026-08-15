"""ChatBI ?? HTTP ???????????????Q-SQL??"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from cogmait_shared.api import SnowflakeID
from cogmait_shared.api.response import ResponseFactory
from cogmait_shared.api.response_schema import EmptyPayload, ResponseSchema
from cogmait_shared.api.service_errors import (
    build_domain_input,
    run_service_call,
    success_response,
)
from cogmait_shared.security import SessionContext

from ...core import deps as core_deps
from ...core.security import get_default_session
from ...domain.system.chatbi import (
    BenchmarkCaseListParams,
    BenchmarkDatasetDatasourceUpsertInput,
    BenchmarkMethodConfig,
    BenchmarkRunCreateInput,
    BenchmarkRunListParams,
    ChatbiBusinessKnowledgeCreateInput,
    ChatbiBusinessKnowledgeDeleteInput,
    ChatbiBusinessKnowledgeListParams,
    ChatbiBusinessKnowledgeUpdateInput,
    ChatbiDatasourceCreateInput,
    ChatbiDatasourceDeleteInput,
    ChatbiDatasourceExecuteSqlInput,
    ChatbiDatasourceFromFilesInput,
    ChatbiDatasourceListParams,
    ChatbiDatasourcePreprocessInput,
    ChatbiDatasourceUpdateInput,
    ChatbiQsqlCreateInput,
    ChatbiQsqlDeleteInput,
    ChatbiQsqlListParams,
    ChatbiQsqlUpdateInput,
)
from ...domain.system.chatbi.query import ChatbiQueryRunInput, ChatbiQueryRunOptions
from ...schemas.system.chatbi.benchmark import (
    BenchmarkCaseListQuery,
    BenchmarkCaseListResponse,
    BenchmarkCaseResultOut,
    BenchmarkDatasetDatasourceListResponse,
    BenchmarkDatasetDatasourceOut,
    BenchmarkDatasetDatasourceUpsertRequest,
    BenchmarkDatasetListResponse,
    BenchmarkDatasetOut,
    BenchmarkRerunNonSuccessOut,
    BenchmarkRunCreateRequest,
    BenchmarkRunDetailOut,
    BenchmarkRunListQuery,
    BenchmarkRunListResponse,
    BenchmarkRunOut,
)
from ...schemas.system.chatbi.business_knowledge import (
    ChatbiBusinessKnowledgeCreateRequest,
    ChatbiBusinessKnowledgeListQuery,
    ChatbiBusinessKnowledgeListResponse,
    ChatbiBusinessKnowledgeRecordOut,
    ChatbiBusinessKnowledgeUpdateRequest,
)
from ...schemas.system.chatbi.datasource import (
    ChatbiDatasourceCreateRequest,
    ChatbiDatasourceExecuteSqlRequest,
    ChatbiDatasourceExecuteSqlResponse,
    ChatbiDatasourceFromFilesRequest,
    ChatbiDatasourceListQuery,
    ChatbiDatasourceListResponse,
    ChatbiDatasourcePreprocessResponse,
    ChatbiDatasourceRecordOut,
    ChatbiDatasourceUpdateRequest,
)
from ...schemas.system.chatbi.qsql import (
    ChatbiQsqlCreateRequest,
    ChatbiQsqlListQuery,
    ChatbiQsqlListResponse,
    ChatbiQsqlRecordOut,
    ChatbiQsqlUpdateRequest,
)
from ...schemas.system.chatbi.query import ChatbiQueryLogDetailOut, ChatbiQueryStreamRequest
from ...services.system.chatbi.benchmark_service import (
    ChatbiBenchmarkService,
    ChatbiBenchmarkServiceError,
)
from ...services.system.chatbi.business_knowledge_service import (
    ChatbiBusinessKnowledgeService,
    ChatbiBusinessKnowledgeServiceError,
)
from ...services.system.chatbi.datasource_service import (
    ChatbiDatasourceService,
    ChatbiDatasourceServiceError,
)
from ...services.system.chatbi.qsql_service import ChatbiQsqlService, ChatbiQsqlServiceError
from ...services.system.chatbi.query_service import ChatbiQueryService, ChatbiQueryServiceError
from ..helpers.chatbi_stream import current_request_id, stream_chatbi_query_events

router = APIRouter(prefix="/chatbi", tags=["chatbi"])


# --- ??? ---


@router.get(
    "/datasource",
    response_model=ResponseSchema[ChatbiDatasourceListResponse],
)
async def list_chatbi_datasources(
    query: ChatbiDatasourceListQuery = Depends(),
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """???? ChatBI ??????"""
    params = build_domain_input(
        lambda: ChatbiDatasourceListParams(
            user_id=session.user_id,
            page=query.page,
            size=query.page_size,
            name_keyword=query.name,
            connector_type_filter=query.connector_type,
        ),
        response_factory=response_factory,
        error_builder=ChatbiDatasourceServiceError.bad_request,
    )
    records, total = await run_service_call(
        service.list_datasources(params),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    payload = _build_page_response(
        response_type=ChatbiDatasourceListResponse,
        record_type=ChatbiDatasourceRecordOut,
        records=records,
        total=total,
        page=params.page,
        size=params.size,
    )
    return success_response(response_factory, data=payload)


@router.post(
    "/datasource",
    response_model=ResponseSchema[ChatbiDatasourceRecordOut],
)
async def create_chatbi_datasource(
    body: ChatbiDatasourceCreateRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """???????????"""
    payload = build_domain_input(
        lambda: ChatbiDatasourceCreateInput(
            user_id=session.user_id,
            name=body.name,
            connector_type=body.connector_type,
            host=body.host,
            port=body.port,
            database=body.database,
            schema_name=body.schema_name,
            username=body.username,
            password=body.password,
            extra_params=dict(body.extra_params or {}),
            remark=body.remark,
        ),
        response_factory=response_factory,
        error_builder=ChatbiDatasourceServiceError.bad_request,
    )
    record = await run_service_call(
        service.create_external(payload),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiDatasourceRecordOut.model_validate(record),
    )


@router.post(
    "/datasource/from-files",
    response_model=ResponseSchema[ChatbiDatasourceRecordOut],
)
async def create_chatbi_datasource_from_files(
    body: ChatbiDatasourceFromFilesRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """?????????????"""
    payload = build_domain_input(
        lambda: ChatbiDatasourceFromFilesInput(
            user_id=session.user_id,
            name=body.name,
            file_ids=list(body.file_ids),
            remark=body.remark,
        ),
        response_factory=response_factory,
        error_builder=ChatbiDatasourceServiceError.bad_request,
    )
    record = await run_service_call(
        service.create_from_files(payload),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiDatasourceRecordOut.model_validate(record),
    )


@router.get(
    "/datasource/{datasource_id}",
    response_model=ResponseSchema[ChatbiDatasourceRecordOut],
)
async def get_chatbi_datasource(
    datasource_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """?? ChatBI ??????"""
    record = await run_service_call(
        service.get_detail(int(datasource_id), session.user_id),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiDatasourceRecordOut.model_validate(record),
    )


@router.put(
    "/datasource/{datasource_id}",
    response_model=ResponseSchema[ChatbiDatasourceRecordOut],
)
async def update_chatbi_datasource(
    datasource_id: SnowflakeID,
    body: ChatbiDatasourceUpdateRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """?? ChatBI ??????"""
    payload = build_domain_input(
        _build_datasource_update_input,
        {
            "body": body,
            "user_id": session.user_id,
        },
        response_factory=response_factory,
        error_builder=ChatbiDatasourceServiceError.bad_request,
    )
    record = await run_service_call(
        service.update_datasource(int(datasource_id), payload),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiDatasourceRecordOut.model_validate(record),
    )


@router.delete(
    "/datasource/{datasource_id}",
    response_model=ResponseSchema[EmptyPayload],
)
async def delete_chatbi_datasource(
    datasource_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """?? ChatBI ????"""
    payload = ChatbiDatasourceDeleteInput(
        user_id=session.user_id,
        datasource_id=int(datasource_id),
    )
    await run_service_call(
        service.delete_datasource(payload),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    return success_response(response_factory, data=EmptyPayload())


@router.post(
    "/datasource/{datasource_id}/test-connection",
    response_model=ResponseSchema[EmptyPayload],
)
async def test_chatbi_datasource_connection(
    datasource_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """????????????"""
    await run_service_call(
        service.test_connection(int(datasource_id), session.user_id),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    return success_response(response_factory, data=EmptyPayload())


@router.post(
    "/datasource/{datasource_id}/preprocess",
    response_model=ResponseSchema[ChatbiDatasourcePreprocessResponse],
)
async def preprocess_chatbi_datasource(
    datasource_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """?????????????"""
    payload = ChatbiDatasourcePreprocessInput(
        user_id=session.user_id,
        datasource_id=int(datasource_id),
    )
    raw = await run_service_call(
        service.enqueue_preprocess(payload),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    data = ChatbiDatasourcePreprocessResponse.model_validate(raw)
    return success_response(response_factory, data=data)


@router.post(
    "/datasource/{datasource_id}/execute-sql",
    response_model=ResponseSchema[ChatbiDatasourceExecuteSqlResponse],
)
async def execute_chatbi_datasource_sql(
    datasource_id: SnowflakeID,
    body: ChatbiDatasourceExecuteSqlRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiDatasourceService = Depends(core_deps.get_chatbi_datasource_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """???? SQL ???????"""
    payload = build_domain_input(
        lambda: ChatbiDatasourceExecuteSqlInput(
            user_id=session.user_id,
            datasource_id=int(datasource_id),
            sql=body.sql,
        ),
        response_factory=response_factory,
        error_builder=ChatbiDatasourceServiceError.bad_request,
    )
    columns, rows, truncated = await run_service_call(
        service.execute_readonly_sql(payload),
        response_factory=response_factory,
        error_type=ChatbiDatasourceServiceError,
    )
    out = ChatbiDatasourceExecuteSqlResponse(columns=columns, rows=rows, truncated=truncated)
    return success_response(response_factory, data=out)


# --- ???? ---


@router.get(
    "/benchmarks/datasets",
    response_model=ResponseSchema[BenchmarkDatasetListResponse],
)
async def list_chatbi_benchmark_datasets(
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    records = await run_service_call(
        service.list_datasets(),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    payload = BenchmarkDatasetListResponse.model_validate(
        {"records": [BenchmarkDatasetOut.model_validate(record) for record in records]}
    )
    return success_response(response_factory, data=payload)


@router.get(
    "/benchmarks/datasets/{dataset_id}/datasources",
    response_model=ResponseSchema[BenchmarkDatasetDatasourceListResponse],
)
async def list_chatbi_benchmark_dataset_datasources(
    dataset_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    records = await run_service_call(
        service.list_dataset_datasources(int(dataset_id)),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    payload = BenchmarkDatasetDatasourceListResponse.model_validate(
        {"records": [BenchmarkDatasetDatasourceOut.model_validate(record) for record in records]}
    )
    return success_response(response_factory, data=payload)


@router.post(
    "/benchmarks/datasets/{dataset_id}/datasources",
    response_model=ResponseSchema[BenchmarkDatasetDatasourceOut],
)
async def upsert_chatbi_benchmark_dataset_datasource(
    dataset_id: SnowflakeID,
    body: BenchmarkDatasetDatasourceUpsertRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = build_domain_input(
        lambda: BenchmarkDatasetDatasourceUpsertInput(
            user_id=session.user_id,
            dataset_id=int(dataset_id),
            datasource_id=int(body.datasource_id),
            db_id=body.db_id,
            display_name=body.display_name,
            status=body.status,
            sort_order=body.sort_order,
        ),
        response_factory=response_factory,
        error_builder=ChatbiBenchmarkServiceError.bad_request,
    )
    record = await run_service_call(
        service.upsert_dataset_datasource(payload),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(
        response_factory,
        data=BenchmarkDatasetDatasourceOut.model_validate(record),
    )


@router.post("/benchmarks/runs", response_model=ResponseSchema[BenchmarkRunOut])
async def create_chatbi_benchmark_run(
    body: BenchmarkRunCreateRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = build_domain_input(
        _build_benchmark_run_create_input,
        {"body": body, "user_id": session.user_id},
        response_factory=response_factory,
        error_builder=ChatbiBenchmarkServiceError.bad_request,
    )
    record = await run_service_call(
        service.create_run(payload),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(response_factory, data=BenchmarkRunOut.model_validate(record))


@router.get("/benchmarks/runs", response_model=ResponseSchema[BenchmarkRunListResponse])
async def list_chatbi_benchmark_runs(
    query: BenchmarkRunListQuery = Depends(),
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    params = build_domain_input(
        lambda: BenchmarkRunListParams(
            user_id=session.user_id,
            page=query.page,
            size=query.page_size,
            dataset_id=int(query.dataset_id) if query.dataset_id is not None else None,
            status=query.status,
        ),
        response_factory=response_factory,
        error_builder=ChatbiBenchmarkServiceError.bad_request,
    )
    records, total = await run_service_call(
        service.list_runs(params),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    payload = _build_page_response(
        response_type=BenchmarkRunListResponse,
        record_type=BenchmarkRunOut,
        records=records,
        total=total,
        page=params.page,
        size=params.size,
    )
    return success_response(response_factory, data=payload)


@router.get(
    "/benchmarks/runs/{run_id}",
    response_model=ResponseSchema[BenchmarkRunDetailOut],
)
async def get_chatbi_benchmark_run(
    run_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    run, metrics = await run_service_call(
        service.get_run_detail(run_id=int(run_id), user_id=session.user_id),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(
        response_factory,
        data=BenchmarkRunDetailOut.model_validate({"run": run, "metrics": metrics}),
    )


@router.get(
    "/benchmarks/runs/{run_id}/cases",
    response_model=ResponseSchema[BenchmarkCaseListResponse],
)
async def list_chatbi_benchmark_cases(
    run_id: SnowflakeID,
    query: BenchmarkCaseListQuery = Depends(),
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    params = build_domain_input(
        lambda: BenchmarkCaseListParams(
            run_id=int(run_id),
            user_id=session.user_id,
            page=query.page,
            size=query.page_size,
            status=query.status,
        ),
        response_factory=response_factory,
        error_builder=ChatbiBenchmarkServiceError.bad_request,
    )
    records, total = await run_service_call(
        service.list_cases(params),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    payload = _build_page_response(
        response_type=BenchmarkCaseListResponse,
        record_type=BenchmarkCaseResultOut,
        records=records,
        total=total,
        page=params.page,
        size=params.size,
    )
    return success_response(response_factory, data=payload)


@router.get(
    "/benchmarks/runs/{run_id}/cases/{result_id}",
    response_model=ResponseSchema[BenchmarkCaseResultOut],
)
async def get_chatbi_benchmark_case(
    run_id: SnowflakeID,
    result_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    record = await run_service_call(
        service.get_case_result(
            run_id=int(run_id),
            result_id=int(result_id),
            user_id=session.user_id,
        ),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(response_factory, data=BenchmarkCaseResultOut.model_validate(record))


@router.post(
    "/benchmarks/runs/{run_id}/cases/rerun-non-success",
    response_model=ResponseSchema[BenchmarkRerunNonSuccessOut],
)
async def rerun_chatbi_benchmark_non_success_cases(
    run_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    result = await run_service_call(
        service.rerun_non_success_cases(
            run_id=int(run_id),
            user_id=session.user_id,
        ),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(
        response_factory,
        data=BenchmarkRerunNonSuccessOut.model_validate(result),
    )


@router.post(
    "/benchmarks/runs/{run_id}/cases/{result_id}/rerun",
    response_model=ResponseSchema[BenchmarkCaseResultOut],
)
async def rerun_chatbi_benchmark_case(
    run_id: SnowflakeID,
    result_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    record = await run_service_call(
        service.rerun_case(
            run_id=int(run_id),
            result_id=int(result_id),
            user_id=session.user_id,
        ),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(response_factory, data=BenchmarkCaseResultOut.model_validate(record))


@router.post(
    "/benchmarks/runs/{run_id}/cancel",
    response_model=ResponseSchema[EmptyPayload],
)
async def cancel_chatbi_benchmark_run(
    run_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    await run_service_call(
        service.cancel_run(run_id=int(run_id), user_id=session.user_id),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(response_factory, data=EmptyPayload())


@router.post(
    "/benchmarks/runs/{run_id}/recover",
    response_model=ResponseSchema[EmptyPayload],
)
async def recover_chatbi_benchmark_run(
    run_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    await run_service_call(
        service.recover_run(run_id=int(run_id), user_id=session.user_id),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(response_factory, data=EmptyPayload())


@router.post(
    "/benchmarks/runs/{run_id}/resume",
    response_model=ResponseSchema[BenchmarkRunOut],
)
async def resume_chatbi_benchmark_run(
    run_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """续跑评价任务：保留已完成样本，仅调度剩余样本。"""
    record = await run_service_call(
        service.resume_run(run_id=int(run_id), user_id=session.user_id),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(response_factory, data=BenchmarkRunOut.model_validate(record))


@router.delete(
    "/benchmarks/runs/{run_id}",
    response_model=ResponseSchema[EmptyPayload],
)
async def delete_chatbi_benchmark_run(
    run_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBenchmarkService = Depends(core_deps.get_chatbi_benchmark_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    await run_service_call(
        service.delete_run(run_id=int(run_id), user_id=session.user_id),
        response_factory=response_factory,
        error_type=ChatbiBenchmarkServiceError,
    )
    return success_response(response_factory, data=EmptyPayload())


# --- ?? ---


@router.post("/query/stream")
async def chatbi_query_stream(
    body: ChatbiQueryStreamRequest,
    session: SessionContext = Depends(get_default_session),
    service_factory: core_deps.ChatbiQueryServiceStreamFactory = Depends(
        core_deps.get_chatbi_query_service_stream_factory
    ),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> StreamingResponse:
    """ChatBI ?? SSE ??"""

    payload = build_domain_input(
        lambda: ChatbiQueryRunInput(
            user_id=session.user_id,
            question=body.question,
            datasource_id=body.datasource_id,
            session_id=body.session_id,
            clarification_token=body.clarification_token,
            clarification_skip=body.clarification_skip,
            request_id=current_request_id(),
            options=ChatbiQueryRunOptions(
                sql_candidate_paths=body.sql_candidate_paths,
                sql_selection_enabled=(
                    True if body.sql_selection_enabled is None else bool(body.sql_selection_enabled)
                ),
                sql_validate_enabled=(
                    True if body.sql_validate_enabled is None else bool(body.sql_validate_enabled)
                ),
                value_founding_enabled=(
                    True
                    if body.value_founding_enabled is None
                    else bool(body.value_founding_enabled)
                ),
                value_search_enabled=bool(body.value_search_enabled)
                if body.value_search_enabled is not None
                else False,
                group_by_audit_enabled=bool(body.group_by_audit_enabled)
                if body.group_by_audit_enabled is not None
                else False,
                rewrite_enabled=(
                    True if body.rewrite_enabled is None else bool(body.rewrite_enabled)
                ),
                summary_enabled=(
                    True if body.summary_enabled is None else bool(body.summary_enabled)
                ),
                business_knowledge_recall_enabled=(
                    True
                    if body.business_knowledge_recall_enabled is None
                    else bool(body.business_knowledge_recall_enabled)
                ),
                schema_selection_enabled=(
                    True
                    if body.schema_selection_enabled is None
                    else bool(body.schema_selection_enabled)
                ),
                qsql_recall_enabled=(
                    True if body.qsql_recall_enabled is None else bool(body.qsql_recall_enabled)
                ),
                sql_fix_enabled=(
                    True if body.sql_fix_enabled is None else bool(body.sql_fix_enabled)
                ),
                rag_enabled=bool(body.rag_enabled) if body.rag_enabled is not None else False,
            ),
        ),
        response_factory=response_factory,
        error_builder=ChatbiQueryServiceError.bad_request,
    )
    return StreamingResponse(
        stream_chatbi_query_events(service_factory, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/messages/{message_id}",
    response_model=ResponseSchema[ChatbiQueryLogDetailOut],
)
async def get_chatbi_query_log_by_message(
    message_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiQueryService = Depends(core_deps.get_chatbi_query_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    """????? ID ?????????"""
    record = await run_service_call(
        service.get_query_log_by_assistant_message(
            message_id=int(message_id),
            user_id=session.user_id,
        ),
        response_factory=response_factory,
        error_type=ChatbiQueryServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiQueryLogDetailOut.model_validate(record),
    )


# --- ???? ---


@router.get(
    "/business-knowledge",
    response_model=ResponseSchema[ChatbiBusinessKnowledgeListResponse],
)
async def list_chatbi_business_knowledge(
    query: ChatbiBusinessKnowledgeListQuery = Depends(),
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBusinessKnowledgeService = Depends(
        core_deps.get_chatbi_business_knowledge_service
    ),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    params = build_domain_input(
        lambda: ChatbiBusinessKnowledgeListParams(
            user_id=session.user_id,
            page=query.page,
            size=query.page_size,
            scope=query.scope,
            kind=query.kind,
            datasource_id=query.datasource_id,
        ),
        response_factory=response_factory,
        error_builder=ChatbiBusinessKnowledgeServiceError.bad_request,
    )
    records, total = await run_service_call(
        service.list_records(params),
        response_factory=response_factory,
        error_type=ChatbiBusinessKnowledgeServiceError,
    )
    payload = _build_page_response(
        response_type=ChatbiBusinessKnowledgeListResponse,
        record_type=ChatbiBusinessKnowledgeRecordOut,
        records=records,
        total=total,
        page=params.page,
        size=params.size,
    )
    return success_response(response_factory, data=payload)


@router.post(
    "/business-knowledge",
    response_model=ResponseSchema[ChatbiBusinessKnowledgeRecordOut],
)
async def create_chatbi_business_knowledge(
    body: ChatbiBusinessKnowledgeCreateRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBusinessKnowledgeService = Depends(
        core_deps.get_chatbi_business_knowledge_service
    ),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = build_domain_input(
        lambda: ChatbiBusinessKnowledgeCreateInput(
            user_id=session.user_id,
            content=body.content,
            scope=body.scope,
            kind=body.kind,
            datasource_id=body.datasource_id,
        ),
        response_factory=response_factory,
        error_builder=ChatbiBusinessKnowledgeServiceError.bad_request,
    )
    record = await run_service_call(
        service.create_record(payload),
        response_factory=response_factory,
        error_type=ChatbiBusinessKnowledgeServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiBusinessKnowledgeRecordOut.model_validate(record),
    )


@router.get(
    "/business-knowledge/{record_id}",
    response_model=ResponseSchema[ChatbiBusinessKnowledgeRecordOut],
)
async def get_chatbi_business_knowledge(
    record_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBusinessKnowledgeService = Depends(
        core_deps.get_chatbi_business_knowledge_service
    ),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    record = await run_service_call(
        service.get_record(int(record_id), session.user_id),
        response_factory=response_factory,
        error_type=ChatbiBusinessKnowledgeServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiBusinessKnowledgeRecordOut.model_validate(record),
    )


@router.put(
    "/business-knowledge/{record_id}",
    response_model=ResponseSchema[ChatbiBusinessKnowledgeRecordOut],
)
async def update_chatbi_business_knowledge(
    record_id: SnowflakeID,
    body: ChatbiBusinessKnowledgeUpdateRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBusinessKnowledgeService = Depends(
        core_deps.get_chatbi_business_knowledge_service
    ),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = build_domain_input(
        _build_business_knowledge_update_input,
        {
            "body": body,
            "record_id": int(record_id),
            "user_id": session.user_id,
        },
        response_factory=response_factory,
        error_builder=ChatbiBusinessKnowledgeServiceError.bad_request,
    )
    record = await run_service_call(
        service.update_record(payload),
        response_factory=response_factory,
        error_type=ChatbiBusinessKnowledgeServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiBusinessKnowledgeRecordOut.model_validate(record),
    )


@router.delete(
    "/business-knowledge/{record_id}",
    response_model=ResponseSchema[EmptyPayload],
)
async def delete_chatbi_business_knowledge(
    record_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiBusinessKnowledgeService = Depends(
        core_deps.get_chatbi_business_knowledge_service
    ),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = ChatbiBusinessKnowledgeDeleteInput(
        user_id=session.user_id,
        record_id=int(record_id),
    )
    await run_service_call(
        service.delete_record(payload),
        response_factory=response_factory,
        error_type=ChatbiBusinessKnowledgeServiceError,
    )
    return success_response(response_factory, data=EmptyPayload())


# --- Q-SQL ---


@router.get("/qsql", response_model=ResponseSchema[ChatbiQsqlListResponse])
async def list_chatbi_qsql(
    query: ChatbiQsqlListQuery = Depends(),
    session: SessionContext = Depends(get_default_session),
    service: ChatbiQsqlService = Depends(core_deps.get_chatbi_qsql_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    params = build_domain_input(
        lambda: ChatbiQsqlListParams(
            user_id=session.user_id,
            page=query.page,
            size=query.page_size,
            datasource_id=query.datasource_id,
        ),
        response_factory=response_factory,
        error_builder=ChatbiQsqlServiceError.bad_request,
    )
    records, total = await run_service_call(
        service.list_qsql(params),
        response_factory=response_factory,
        error_type=ChatbiQsqlServiceError,
    )
    payload = _build_page_response(
        response_type=ChatbiQsqlListResponse,
        record_type=ChatbiQsqlRecordOut,
        records=records,
        total=total,
        page=params.page,
        size=params.size,
    )
    return success_response(response_factory, data=payload)


@router.post("/qsql", response_model=ResponseSchema[ChatbiQsqlRecordOut])
async def create_chatbi_qsql(
    body: ChatbiQsqlCreateRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiQsqlService = Depends(core_deps.get_chatbi_qsql_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = build_domain_input(
        lambda: ChatbiQsqlCreateInput(
            user_id=session.user_id,
            datasource_id=body.datasource_id,
            question=body.question,
            sql_body=body.sql_body,
        ),
        response_factory=response_factory,
        error_builder=ChatbiQsqlServiceError.bad_request,
    )
    record = await run_service_call(
        service.create_qsql(payload),
        response_factory=response_factory,
        error_type=ChatbiQsqlServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiQsqlRecordOut.model_validate(record),
    )


@router.get("/qsql/{record_id}", response_model=ResponseSchema[ChatbiQsqlRecordOut])
async def get_chatbi_qsql(
    record_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiQsqlService = Depends(core_deps.get_chatbi_qsql_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    record = await run_service_call(
        service.get_qsql(int(record_id), session.user_id),
        response_factory=response_factory,
        error_type=ChatbiQsqlServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiQsqlRecordOut.model_validate(record),
    )


@router.put("/qsql/{record_id}", response_model=ResponseSchema[ChatbiQsqlRecordOut])
async def update_chatbi_qsql(
    record_id: SnowflakeID,
    body: ChatbiQsqlUpdateRequest,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiQsqlService = Depends(core_deps.get_chatbi_qsql_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = build_domain_input(
        _build_qsql_update_input,
        {
            "body": body,
            "record_id": int(record_id),
            "user_id": session.user_id,
        },
        response_factory=response_factory,
        error_builder=ChatbiQsqlServiceError.bad_request,
    )
    record = await run_service_call(
        service.update_qsql(payload),
        response_factory=response_factory,
        error_type=ChatbiQsqlServiceError,
    )
    return success_response(
        response_factory,
        data=ChatbiQsqlRecordOut.model_validate(record),
    )


@router.delete("/qsql/{record_id}", response_model=ResponseSchema[EmptyPayload])
async def delete_chatbi_qsql(
    record_id: SnowflakeID,
    session: SessionContext = Depends(get_default_session),
    service: ChatbiQsqlService = Depends(core_deps.get_chatbi_qsql_service),
    response_factory: ResponseFactory = Depends(core_deps.get_response_factory),
) -> object:
    payload = ChatbiQsqlDeleteInput(user_id=session.user_id, record_id=int(record_id))
    await run_service_call(
        service.delete_qsql(payload),
        response_factory=response_factory,
        error_type=ChatbiQsqlServiceError,
    )
    return success_response(response_factory, data=EmptyPayload())


# --- ???? ---


def _build_benchmark_run_create_input(
    *,
    body: BenchmarkRunCreateRequest,
    user_id: int,
) -> BenchmarkRunCreateInput:
    method_config = body.method_config
    return BenchmarkRunCreateInput(
        user_id=user_id,
        dataset_id=int(body.dataset_id),
        method_type=body.method_type,
        method_config=BenchmarkMethodConfig(
            model=method_config.model if method_config is not None else "default",
            prompt_version=(
                method_config.prompt_version if method_config is not None else "default"
            ),
            schema_selection_enabled=(
                method_config.schema_selection_enabled if method_config is not None else True
            ),
            qsql_recall_enabled=(
                method_config.qsql_recall_enabled if method_config is not None else True
            ),
            business_knowledge_recall_enabled=(
                method_config.business_knowledge_recall_enabled
                if method_config is not None
                else True
            ),
            sql_fix_enabled=method_config.sql_fix_enabled if method_config is not None else True,
            evidence_enabled=(
                method_config.evidence_enabled if method_config is not None else False
            ),
            sql_candidate_paths=(
                method_config.sql_candidate_paths
                if method_config is not None
                else ["ddl:chain_of_thought"]
            ),
            sql_selection_enabled=(
                method_config.sql_selection_enabled if method_config is not None else True
            ),
            sql_validate_enabled=(
                method_config.sql_validate_enabled if method_config is not None else True
            ),
            rewrite_enabled=(
                method_config.rewrite_enabled if method_config is not None else True
            ),
            summary_enabled=(
                method_config.summary_enabled if method_config is not None else True
            ),
            schema_top_k=method_config.schema_top_k if method_config is not None else None,
            schema_full_if_small=(
                method_config.schema_full_if_small if method_config is not None else False
            ),
            schema_small_table_threshold=(
                method_config.schema_small_table_threshold if method_config is not None else 15
            ),
            sql_fix_max_attempts=(
                method_config.sql_fix_max_attempts if method_config is not None else None
            ),
            value_founding_enabled=(
                method_config.value_founding_enabled if method_config is not None else True
            ),
            value_search_enabled=(
                method_config.value_search_enabled if method_config is not None else False
            ),
            rag_enabled=(
                method_config.rag_enabled if method_config is not None else False
            ),
            group_by_audit_enabled=(
                method_config.group_by_audit_enabled if method_config is not None else False
            ),
        ),
        selected_datasource_ids=(
            [int(item) for item in body.selected_datasource_ids]
            if body.selected_datasource_ids
            else None
        ),
        source_group=body.source_group,
        sample_limit=body.sample_limit,
        concurrency=body.concurrency,
        timeout_seconds=body.timeout_seconds,
    )


def _build_datasource_update_input(
    *,
    body: ChatbiDatasourceUpdateRequest,
    user_id: int,
) -> ChatbiDatasourceUpdateInput:
    """???????????????????"""
    payload_data: dict[str, Any] = body.model_dump(exclude_unset=True)
    provided_fields = frozenset(payload_data)
    if payload_data.get("extra_params") is not None:
        payload_data["extra_params"] = dict(payload_data["extra_params"])
    return ChatbiDatasourceUpdateInput(
        **payload_data,
        user_id=user_id,
        provided_fields=provided_fields,
    )


def _build_business_knowledge_update_input(
    *,
    body: ChatbiBusinessKnowledgeUpdateRequest,
    record_id: int,
    user_id: int,
) -> ChatbiBusinessKnowledgeUpdateInput:
    payload_data: dict[str, Any] = body.model_dump(exclude_unset=True)
    return ChatbiBusinessKnowledgeUpdateInput(
        **payload_data,
        record_id=record_id,
        user_id=user_id,
        provided_fields=frozenset(payload_data),
    )


def _build_qsql_update_input(
    *,
    body: ChatbiQsqlUpdateRequest,
    record_id: int,
    user_id: int,
) -> ChatbiQsqlUpdateInput:
    payload_data: dict[str, Any] = body.model_dump(exclude_unset=True)
    return ChatbiQsqlUpdateInput(
        **payload_data,
        record_id=record_id,
        user_id=user_id,
        provided_fields=frozenset(payload_data),
    )


def _build_page_response(
    *,
    response_type: type[Any],
    record_type: type[Any],
    records: list[Any],
    total: int,
    page: int,
    size: int,
) -> Any:
    """????????????? alias?"""
    return response_type.model_validate(
        {
            "total": total,
            "current": page,
            "pageSize": size,
            "records": [record_type.model_validate(record) for record in records],
        }
    )


__all__ = ["router"]
