"""ChatBI 基准评价服务。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis

from cogmait_shared.core.api_codes import ErrorCode, HttpStatus
from cogmait_shared.db import Database, IntegrityError, UnitOfWork
from cogmait_shared.observability.logging import logger
from cogmait_shared.streaming import RedisStreamPublisher, StreamPayload

from ....constants.chatbi.query import (
    CHATBI_SSE_COMPLETED,
    CHATBI_SSE_DATA,
    CHATBI_SSE_QSQL_RECALL,
    CHATBI_SSE_SQL,
)
from ....core.config import get_settings
from ....domain.system.chatbi import (
    BenchmarkCaseListParams,
    BenchmarkCaseResultRecord,
    BenchmarkCaseStatus,
    BenchmarkDatasetDatasourceRecord,
    BenchmarkDatasetDatasourceUpsertInput,
    BenchmarkDatasetRecord,
    BenchmarkDatasetStatus,
    BenchmarkDatasourceStatus,
    BenchmarkMethodType,
    BenchmarkMetricName,
    BenchmarkMetricSummaryRecord,
    BenchmarkRunCreateInput,
    BenchmarkRunListParams,
    BenchmarkRunRecord,
    BenchmarkRunStatus,
    BenchmarkSampleRecord,
    ChatbiQueryRunInput,
    ChatbiQueryRunOptions,
    ChatbiQueryStreamEvent,
)
from ....repositories.system.chatbi import ChatbiBenchmarkRepository, ChatbiDatasourceRepository
from ..llm_service import LLMService
from ..rewrite import RewriteService
from ..service_error import ServiceError
from .benchmark import (
    build_benchmark_question,
    build_reference_json,
    compute_benchmark_metrics,
    connector_type_to_dialect,
)
from .datasource.credential_encryption_service import ChatbiCredentialEncryptionService
from .datasource.db_connection_service import ChatbiDbConnectionService
from .datasource_errors import ChatbiDatasourceServiceError
from .dinsql import DinSqlRunner
from .multi_agent import MultiAgentSqlRunner
from .query.prompts import json_safe_rows
from .query.stream_event_serializer import serialize_chatbi_stream_event
from .query_service import ChatbiQueryService
from .single_agent import SingleAgentSqlRunner

CHATBI_BENCHMARK_TASK_STREAM = "chatbi:benchmark:tasks"
CHATBI_BENCHMARK_STREAM_TASK_TYPE = "chatbi_benchmark_run"
CHATBI_BENCHMARK_TASK_ACTION_RERUN_CASE = "rerun_case"
_BENCHMARK_SSE_DATA_PREVIEW_ROWS = 5
_BENCHMARK_SQL_RESULT_PREVIEW_ROWS = 50


class ChatbiBenchmarkServiceError(ServiceError):
    """ChatBI 基准评价服务异常。"""

    @classmethod
    def bad_request(cls, message: str) -> ChatbiBenchmarkServiceError:
        return cls(message, status_code=HttpStatus.BAD_REQUEST, code=ErrorCode.PARAMS_INVALID)

    @classmethod
    def not_found(cls, message: str = "评价任务不存在") -> ChatbiBenchmarkServiceError:
        return cls(message, status_code=HttpStatus.NOT_FOUND, code=ErrorCode.NOT_FOUND)

    @classmethod
    def status_invalid(cls, message: str) -> ChatbiBenchmarkServiceError:
        return cls(message, status_code=HttpStatus.CONFLICT, code=ErrorCode.STATUS_INVALID)

    @classmethod
    def system_error(cls, message: str) -> ChatbiBenchmarkServiceError:
        return cls(message, status_code=HttpStatus.INTERNAL_ERROR, code=ErrorCode.SYSTEM_ERROR)


@dataclass(slots=True)
class _MethodRunResult:
    generated_sql: str | None
    trace_id: str | None
    stage_latency_ms: dict[str, int]
    token_usage: dict[str, int | None]
    query_stream_events: list[dict[str, Any]]
    raw_output: dict[str, Any]


@dataclass(slots=True)
class _SqlExecution:
    columns: list[str]
    rows: list[dict[str, Any]]
    elapsed_ms: int
    truncated: bool


def _decimal(value: float | None, scale: int = 4) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(float(value), scale)))


def _token_usage_from_stream_event(event: ChatbiQueryStreamEvent) -> dict[str, int | None]:
    if event.total_tokens is None or event.total_tokens <= 0:
        return {}
    return {"total_tokens": event.total_tokens}


def _token_usage_from_stream_payload(payload: dict[str, Any]) -> dict[str, int | None]:
    if payload.get("event") != CHATBI_SSE_COMPLETED:
        return {}
    total = _coerce_optional_int(payload.get("total_tokens"))
    if total is None:
        total = _coerce_optional_int(payload.get("totalTokens"))
    if total is None or total <= 0:
        return {}
    return {"total_tokens": total}


def _qsql_recall_detail(query_stream_events: list[dict[str, Any]]) -> dict[str, Any]:
    for payload in query_stream_events:
        if payload.get("event") != CHATBI_SSE_QSQL_RECALL:
            continue
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
        global_items = [
            item
            for item in items
            if isinstance(item, dict) and str(item.get("scope") or "").upper() == "GLOBAL"
        ]
        strategies = sorted(
            {
                str(item.get("retrievalStrategy"))
                for item in items
                if isinstance(item, dict) and item.get("retrievalStrategy")
            }
        )
        return {
            "enabled": True,
            "count": len(items),
            "global_count": len(global_items),
            "strategies": strategies,
            "items": items,
        }
    return {"enabled": False, "count": 0, "global_count": 0, "strategies": [], "items": []}


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _case_total_tokens(token_usage: dict[str, int | None]) -> int | None:
    if not token_usage:
        return None
    return token_usage.get("total_tokens") or token_usage.get("totalTokens")


def _sql_result_preview(exec_result: _SqlExecution | None) -> dict[str, Any] | None:
    if exec_result is None:
        return None
    safe_rows = json_safe_rows(exec_result.rows)
    preview_rows = safe_rows[:_BENCHMARK_SQL_RESULT_PREVIEW_ROWS]
    row_count = len(safe_rows)
    preview_truncated = row_count > len(preview_rows)
    return {
        "columns": list(exec_result.columns),
        "rows": preview_rows,
        "row_count": row_count,
        "preview_row_count": len(preview_rows),
        "truncated": bool(exec_result.truncated or preview_truncated),
        "elapsed_ms": exec_result.elapsed_ms,
    }


def _benchmark_sql_execution_detail(
    *,
    generated_exec: _SqlExecution | None,
    gold_exec: _SqlExecution | None,
    generated_error: str | None = None,
    gold_error: str | None = None,
) -> dict[str, Any]:
    return {
        "generated_sql_execute_ms": generated_exec.elapsed_ms if generated_exec else None,
        "gold_sql_execute_ms": gold_exec.elapsed_ms if gold_exec else None,
        "generated": _sql_result_preview(generated_exec),
        "gold": _sql_result_preview(gold_exec),
        "generated_error": generated_error,
        "gold_error": gold_error,
    }


class ChatbiBenchmarkService:
    """ChatBI benchmark 业务编排。"""

    def __init__(
        self,
        *,
        unit_of_work: Any,
        redis: Redis,
        llm_service: LLMService,
        rewrite_service: RewriteService,
        database: Database | None = None,
    ) -> None:
        self._uow = unit_of_work
        self._session = unit_of_work.session
        self._redis = redis
        self._llm = llm_service
        self._rewrite = rewrite_service
        self._database = database
        self._repo = ChatbiBenchmarkRepository(self._session)
        self._ds_repo = ChatbiDatasourceRepository(self._session)
        settings = get_settings()
        self._publisher = RedisStreamPublisher(
            redis,
            stream=CHATBI_BENCHMARK_TASK_STREAM,
            key_prefix=settings.redis_key_prefix,
        )
        self._db_conn = ChatbiDbConnectionService(
            datasource_repo=self._ds_repo,
            encryption=ChatbiCredentialEncryptionService(
                key_material=settings.chatbi_datasource_credential_encryption_key,
            ),
        )
        # Optional hook: (run_id, sample_id, sample_code, status, processed/total/success/failed, elapsed_ms)
        self._on_sample_progress: Any | None = None

    async def list_datasets(self) -> list[BenchmarkDatasetRecord]:
        return await self._repo.list_datasets()

    async def list_dataset_datasources(
        self,
        dataset_id: int,
    ) -> list[BenchmarkDatasetDatasourceRecord]:
        if await self._repo.get_dataset(dataset_id) is None:
            raise ChatbiBenchmarkServiceError.not_found("数据集不存在")
        return await self._repo.list_dataset_datasources(dataset_id)

    async def upsert_dataset_datasource(
        self,
        payload: BenchmarkDatasetDatasourceUpsertInput,
    ) -> BenchmarkDatasetDatasourceRecord:
        if await self._repo.get_dataset(payload.dataset_id) is None:
            raise ChatbiBenchmarkServiceError.not_found("数据集不存在")
        datasource = await self._ds_repo.get_by_id(payload.datasource_id)
        if datasource is None:
            raise ChatbiBenchmarkServiceError.bad_request("数据源不存在")
        status = payload.status
        if status is None:
            status = (
                BenchmarkDatasourceStatus.READY.value
                if datasource.db_schema
                else BenchmarkDatasourceStatus.SCHEMA_NOT_READY.value
            )
        link_id = await self._repo.upsert_dataset_datasource(
            dataset_id=payload.dataset_id,
            datasource_id=payload.datasource_id,
            db_id=payload.db_id,
            display_name=payload.display_name,
            status=status,
            sort_order=payload.sort_order,
            user_id=payload.user_id,
        )
        await self._repo.refresh_dataset_datasource_counts(payload.dataset_id)
        await self._repo.refresh_dataset_counts(payload.dataset_id, user_id=payload.user_id)
        await self._commit()
        for item in await self._repo.list_dataset_datasources(payload.dataset_id):
            if item.id == link_id:
                return item
        raise ChatbiBenchmarkServiceError.system_error("数据集数据源关联维护失败")

    async def create_run(self, payload: BenchmarkRunCreateInput) -> BenchmarkRunRecord:
        dataset = await self._load_ready_dataset(payload.dataset_id)
        await self._validate_run_scope(payload)
        total_count = await self._repo.count_samples(
            dataset_id=payload.dataset_id,
            selected_datasource_ids=payload.selected_datasource_ids,
            source_group=payload.source_group,
        )
        method_snapshot = payload.method_config.to_snapshot(payload.method_type)
        if payload.sample_ids:
            total_count = len(payload.sample_ids)
            method_snapshot["_benchmark_sample_ids"] = payload.sample_ids
        elif payload.sample_limit is not None:
            total_count = min(total_count, payload.sample_limit)
        if total_count <= 0:
            raise ChatbiBenchmarkServiceError.bad_request("当前筛选条件下没有可评价样本")
        run_id = await self._repo.create_run(
            dataset=dataset,
            method_type=payload.method_type,
            method_config_snapshot=method_snapshot,
            selected_datasource_ids=payload.selected_datasource_ids,
            source_group=payload.source_group,
            sample_limit=payload.sample_limit,
            concurrency=payload.concurrency,
            timeout_seconds=payload.timeout_seconds,
            total_count=total_count,
            user_id=payload.user_id,
        )
        await self._commit()
        await self._publish_run(run_id)
        record = await self._repo.get_run_for_user(run_id, payload.user_id)
        if record is None:
            raise ChatbiBenchmarkServiceError.system_error("评价任务创建后不存在")
        return record

    async def list_runs(
        self,
        params: BenchmarkRunListParams,
    ) -> tuple[list[BenchmarkRunRecord], int]:
        return await self._repo.list_runs(params)

    async def get_run_detail(
        self,
        *,
        run_id: int,
        user_id: int,
    ) -> tuple[BenchmarkRunRecord, list[BenchmarkMetricSummaryRecord]]:
        run = await self._repo.get_run_for_user(run_id, user_id)
        if run is None:
            raise ChatbiBenchmarkServiceError.not_found()
        return run, await self._repo.list_metric_summaries(run_id)

    async def list_cases(
        self,
        params: BenchmarkCaseListParams,
    ) -> tuple[list[BenchmarkCaseResultRecord], int]:
        if await self._repo.get_run_for_user(params.run_id, params.user_id) is None:
            raise ChatbiBenchmarkServiceError.not_found()
        return await self._repo.list_cases(params)

    async def get_case_result(
        self,
        *,
        run_id: int,
        result_id: int,
        user_id: int,
    ) -> BenchmarkCaseResultRecord:
        if await self._repo.get_run_for_user(run_id, user_id) is None:
            raise ChatbiBenchmarkServiceError.not_found()
        record = await self._repo.get_case_result(run_id=run_id, result_id=result_id)
        if record is None:
            raise ChatbiBenchmarkServiceError.not_found("样本结果不存在")
        return record

    async def cancel_run(self, *, run_id: int, user_id: int) -> None:
        if not await self._repo.cancel_run(run_id, user_id):
            raise ChatbiBenchmarkServiceError.status_invalid("任务不存在或不可取消")
        await self._commit()

    async def recover_run(self, *, run_id: int, user_id: int) -> None:
        if not await self._repo.recover_run(run_id, user_id):
            raise ChatbiBenchmarkServiceError.status_invalid("仅 RUNNING 状态的任务可恢复")
        await self._commit()
        await self._publish_run(run_id)

    async def resume_run(self, *, run_id: int, user_id: int) -> BenchmarkRunRecord:
        """续跑指定任务：保留已完成样本，仅调度剩余样本。"""
        run = await self._repo.get_run_for_user(run_id, user_id)
        if run is None:
            raise ChatbiBenchmarkServiceError.not_found()
        if (
            run.status == BenchmarkRunStatus.SUCCESS.value
            and int(run.processed_count) >= int(run.total_count)
        ):
            raise ChatbiBenchmarkServiceError.status_invalid("任务已完成，无需续跑")
        if run.status not in {
            BenchmarkRunStatus.PENDING.value,
            BenchmarkRunStatus.RUNNING.value,
            BenchmarkRunStatus.FAILED.value,
            BenchmarkRunStatus.CANCELED.value,
            BenchmarkRunStatus.SUCCESS.value,
        }:
            raise ChatbiBenchmarkServiceError.status_invalid("当前状态不可续跑")

        await self._repo.soft_delete_rerunning_cases(run_id, user_id=user_id)
        await self._repo.sync_run_progress_from_cases(run_id, user_id=user_id)
        if not await self._repo.prepare_run_for_resume(run_id, user_id):
            raise ChatbiBenchmarkServiceError.status_invalid("任务不存在或不可续跑")
        await self._commit()

        run = await self._repo.get_run_for_user(run_id, user_id)
        if run is None:
            raise ChatbiBenchmarkServiceError.system_error("续跑提交后任务不存在")
        completed_ids = await self._repo.list_completed_sample_ids(run_id)
        if int(run.total_count) > 0 and len(completed_ids) >= int(run.total_count):
            await self._write_metric_summaries(run)
            await self._repo.finish_run(run_id, status=BenchmarkRunStatus.SUCCESS.value)
            await self._commit()
            record = await self._repo.get_run_for_user(run_id, user_id)
            if record is None:
                raise ChatbiBenchmarkServiceError.system_error("续跑完成后任务不存在")
            return record

        await self._publish_run(run_id)
        record = await self._repo.get_run_for_user(run_id, user_id)
        if record is None:
            raise ChatbiBenchmarkServiceError.system_error("续跑提交后任务不存在")
        return record

    async def delete_run(self, *, run_id: int, user_id: int) -> None:
        if not await self._repo.soft_delete_run(run_id, user_id):
            run = await self._repo.get_run_for_user(run_id, user_id)
            if run is None:
                raise ChatbiBenchmarkServiceError.not_found()
            if run.status in {
                BenchmarkRunStatus.PENDING.value,
                BenchmarkRunStatus.RUNNING.value,
            }:
                raise ChatbiBenchmarkServiceError.status_invalid("运行中的任务请先取消后再删除")
            raise ChatbiBenchmarkServiceError.not_found()
        await self._commit()

    async def rerun_case(
        self,
        *,
        run_id: int,
        result_id: int,
        user_id: int,
    ) -> BenchmarkCaseResultRecord:
        run = await self._repo.get_run_for_user(run_id, user_id)
        if run is None:
            raise ChatbiBenchmarkServiceError.not_found()
        if run.status in {
            BenchmarkRunStatus.PENDING.value,
            BenchmarkRunStatus.RUNNING.value,
        }:
            raise ChatbiBenchmarkServiceError.status_invalid("任务运行中，无法重跑样本")
        case = await self._repo.get_case_result(run_id=run_id, result_id=result_id)
        if case is None:
            raise ChatbiBenchmarkServiceError.not_found("样本结果不存在")
        if case.status == BenchmarkCaseStatus.RERUNNING.value:
            raise ChatbiBenchmarkServiceError.status_invalid("样本正在重跑中")
        sample = await self._repo.get_sample(case.sample_id)
        if sample is None:
            raise ChatbiBenchmarkServiceError.bad_request("样本不存在或已禁用")
        if not await self._repo.mark_case_rerunning(result_id, user_id=user_id):
            raise ChatbiBenchmarkServiceError.status_invalid("样本正在重跑中")
        await self._commit()
        await self._publish_rerun(run_id, result_id)
        record = await self._repo.get_case_result(run_id=run_id, result_id=result_id)
        if record is None:
            raise ChatbiBenchmarkServiceError.system_error("样本重跑提交后不存在")
        return record

    async def rerun_non_success_cases(
        self,
        *,
        run_id: int,
        user_id: int,
    ) -> dict[str, int]:
        run = await self._repo.get_run_for_user(run_id, user_id)
        if run is None:
            raise ChatbiBenchmarkServiceError.not_found()
        if run.status in {
            BenchmarkRunStatus.PENDING.value,
            BenchmarkRunStatus.RUNNING.value,
        }:
            raise ChatbiBenchmarkServiceError.status_invalid("任务运行中，无法重跑样本")
        cases = await self._repo.list_cases_for_run(run_id)
        submitted_ids: list[int] = []
        skipped_count = 0
        for case in cases:
            if case.status in {
                BenchmarkCaseStatus.SUCCESS.value,
                BenchmarkCaseStatus.RERUNNING.value,
            }:
                continue
            sample = await self._repo.get_sample(case.sample_id)
            if sample is None:
                skipped_count += 1
                continue
            if await self._repo.mark_case_rerunning(case.id, user_id=user_id):
                submitted_ids.append(case.id)
            else:
                skipped_count += 1
        if not submitted_ids:
            raise ChatbiBenchmarkServiceError.bad_request("没有可重跑的非成功样本")
        await self._commit()
        for result_id in submitted_ids:
            await self._publish_rerun(run_id, result_id)
        return {
            "submitted_count": len(submitted_ids),
            "skipped_count": skipped_count,
        }

    async def process_rerun_case(self, run_id: int, result_id: int) -> None:
        run = await self._repo.get_run(run_id)
        if run is None:
            return
        case = await self._repo.get_case_result(run_id=run_id, result_id=result_id)
        if case is None or case.status != BenchmarkCaseStatus.RERUNNING.value:
            return
        detail = dict(case.detail_json or {})
        rerun_meta = detail.get("rerun")
        previous_status = (
            rerun_meta.get("previous_status") if isinstance(rerun_meta, dict) else None
        )
        old_status = (
            previous_status
            if isinstance(previous_status, str) and previous_status
            else BenchmarkCaseStatus.EXEC_ERROR.value
        )
        sample = await self._repo.get_sample(case.sample_id)
        if sample is None:
            await self._repo.update_case_result(
                result_id,
                status=BenchmarkCaseStatus.EXEC_ERROR.value,
                error_message="样本不存在或已禁用",
                updated_by=run.created_by,
            )
            await self._commit()
            return
        try:
            values = await self._run_sample(run, sample)
            update_values = {
                key: value
                for key, value in values.items()
                if key not in {"run_id", "sample_id", "created_by"}
            }
            update_values["updated_by"] = run.created_by
            if not await self._repo.update_case_result(result_id, **update_values):
                return
            await self._repo.adjust_run_case_counts(
                run_id,
                old_status=old_status,
                new_status=values["status"],
                last_error=values.get("error_message"),
                user_id=run.created_by,
            )
            await self._write_metric_summaries(run)
            await self._commit()
        except Exception as exc:
            logger.exception(
                "ChatBI benchmark case rerun failed run_id={} result_id={}",
                run_id,
                result_id,
            )
            await self._session.rollback()
            await self._repo.update_case_result(
                result_id,
                status=BenchmarkCaseStatus.EXEC_ERROR.value,
                error_message=str(exc)[:2000],
                updated_by=run.created_by,
            )
            await self._repo.adjust_run_case_counts(
                run_id,
                old_status=old_status,
                new_status=BenchmarkCaseStatus.EXEC_ERROR.value,
                last_error=str(exc)[:2000],
                user_id=run.created_by,
            )
            await self._write_metric_summaries(run)
            await self._commit()

    async def process_run(self, run_id: int) -> None:
        if not await self._repo.mark_run_running(run_id):
            await self._session.rollback()
            return
        await self._commit()
        run = await self._repo.get_run(run_id)
        if run is None:
            return
        try:
            await self._process_run_samples(run)
            run = await self._repo.get_run(run_id)
            if run is None:
                return
            if run.status == BenchmarkRunStatus.CANCELED.value:
                return
            await self._write_metric_summaries(run)
            await self._repo.finish_run(run_id, status=BenchmarkRunStatus.SUCCESS.value)
            await self._commit()
        except Exception as exc:
            logger.exception("ChatBI benchmark run failed run_id={}", run_id)
            await self._session.rollback()
            await self._repo.finish_run(
                run_id,
                status=BenchmarkRunStatus.FAILED.value,
                last_error=str(exc)[:2000],
            )
            await self._commit()

    async def _process_run_samples(self, run: BenchmarkRunRecord) -> None:
        raw_sample_ids = run.method_config_snapshot.get("_benchmark_sample_ids")
        sample_ids: list[int] | None = None
        if raw_sample_ids:
            sample_ids = [int(item) for item in raw_sample_ids]
        samples = await self._repo.list_samples_for_run(
            dataset_id=run.dataset_id,
            selected_datasource_ids=run.selected_datasource_ids,
            source_group=run.source_group,
            limit=run.sample_limit if not sample_ids else None,
            sample_ids=sample_ids,
        )
        completed_ids = await self._repo.list_completed_sample_ids(run.id)
        samples = [sample for sample in samples if sample.id not in completed_ids]
        if not samples:
            return
        concurrency = max(1, min(int(run.concurrency or 1), len(samples) or 1))
        callback = getattr(self, "_on_sample_progress", None)
        if callback is not None:
            callback(
                run_id=run.id,
                sample_id=None,
                sample_code=None,
                status="START",
                processed_count=int(run.processed_count or 0),
                total_count=int(run.total_count or 0),
                success_count=int(run.success_count or 0),
                failed_count=int(run.failed_count or 0),
                elapsed_ms=None,
                remaining=len(samples),
                concurrency=concurrency,
            )
        if concurrency > 1 and self._database is not None:
            await self._commit()
            await self._process_run_samples_concurrently(run, samples, concurrency=concurrency)
            return
        if concurrency > 1:
            logger.warning(
                "ChatBI benchmark concurrency requested but database factory is unavailable; "
                "falling back to sequential processing run_id={} concurrency={}",
                run.id,
                concurrency,
            )
        for sample in samples:
            processed = await self._process_run_sample_in_current_session(run, sample)
            if not processed:
                return

    async def _process_run_samples_concurrently(
        self,
        run: BenchmarkRunRecord,
        samples: list[BenchmarkSampleRecord],
        *,
        concurrency: int,
    ) -> None:
        queue: asyncio.Queue[BenchmarkSampleRecord] = asyncio.Queue()
        for sample in samples:
            queue.put_nowait(sample)
        canceled = asyncio.Event()

        async def worker(worker_index: int) -> None:
            while not canceled.is_set():
                try:
                    sample = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    processed = await self._process_run_sample_in_new_session(run, sample)
                    if not processed:
                        canceled.set()
                except Exception as exc:
                    logger.exception(
                        "ChatBI benchmark concurrent sample failed run_id={} worker={} sample_id={}",
                        run.id,
                        worker_index,
                        sample.id,
                    )
                    await self._write_sample_exception_in_new_session(run, sample, exc)
                finally:
                    queue.task_done()

        tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def _process_run_sample_in_current_session(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
    ) -> bool:
        current = await self._repo.get_run(run.id)
        if current is None or current.status == BenchmarkRunStatus.CANCELED.value:
            return False
        values = await self._run_sample(run, sample)
        current = await self._repo.get_run(run.id)
        if current is None or current.status == BenchmarkRunStatus.CANCELED.value:
            return False
        await self._repo.create_case_result(**values)
        success_delta = 1 if values["status"] == BenchmarkCaseStatus.SUCCESS.value else 0
        failed_delta = 0 if success_delta else 1
        await self._repo.update_run_progress(
            run.id,
            success_delta=success_delta,
            failed_delta=failed_delta,
            last_error=values.get("error_message"),
        )
        await self._commit()
        callback = getattr(self, "_on_sample_progress", None)
        if callback is not None:
            current = await self._repo.get_run(run.id)
            if current is not None:
                callback(
                    run_id=run.id,
                    sample_id=sample.id,
                    sample_code=sample.sample_code,
                    status=values["status"],
                    processed_count=int(current.processed_count or 0),
                    total_count=int(current.total_count or 0),
                    success_count=int(current.success_count or 0),
                    failed_count=int(current.failed_count or 0),
                    elapsed_ms=values.get("elapsed_ms"),
                )
        return True

    async def _process_run_sample_in_new_session(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
    ) -> bool:
        if self._database is None:
            return await self._process_run_sample_in_current_session(run, sample)
        async with self._database.get_session() as session:
            child = ChatbiBenchmarkService(
                unit_of_work=UnitOfWork(session),
                redis=self._redis,
                llm_service=self._llm,
                rewrite_service=self._rewrite,
                database=self._database,
            )
            child._on_sample_progress = getattr(self, "_on_sample_progress", None)
            return await child._process_run_sample_in_current_session(run, sample)

    async def _write_sample_exception_in_new_session(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
        exc: Exception,
    ) -> None:
        if self._database is None:
            raise exc
        async with self._database.get_session() as session:
            child = ChatbiBenchmarkService(
                unit_of_work=UnitOfWork(session),
                redis=self._redis,
                llm_service=self._llm,
                rewrite_service=self._rewrite,
                database=self._database,
            )
            child._on_sample_progress = getattr(self, "_on_sample_progress", None)
            await child._write_sample_exception(run, sample, exc)

    async def _write_sample_exception(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
        exc: Exception,
    ) -> None:
        current = await self._repo.get_run(run.id)
        if current is None or current.status == BenchmarkRunStatus.CANCELED.value:
            return
        now = datetime.now().astimezone()
        message = str(exc)[:2000]
        values = {
            "run_id": run.id,
            "sample_id": sample.id,
            "dataset_id": sample.dataset_id,
            "datasource_id": sample.datasource_id,
            "sample_code": sample.sample_code,
            "question_snapshot": build_benchmark_question(
                sample.question,
                sample.evidence,
                evidence_enabled=_snapshot_bool(
                    run.method_config_snapshot,
                    "evidence_enabled",
                    "evidenceEnabled",
                    default=False,
                ),
            ),
            "gold_sql_snapshot": sample.gold_sql,
            "generated_sql": None,
            "execution_accuracy": None,
            "table_f1": None,
            "column_f1": None,
            "join_f1": None,
            "domain_knowledge_f1": None,
            "status": BenchmarkCaseStatus.EXEC_ERROR.value,
            "error_message": message,
            "trace_id": None,
            "detail_json": {"error": {"message": message}},
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "generated_sql_execute_ms": None,
            "gold_sql_execute_ms": None,
            "started_at": now,
            "finished_at": now,
            "elapsed_ms": 0,
            "created_by": run.created_by,
            "updated_by": run.created_by,
        }
        await self._repo.create_case_result(**values)
        await self._repo.update_run_progress(
            run.id,
            success_delta=0,
            failed_delta=1,
            last_error=message,
        )
        await self._commit()
        callback = getattr(self, "_on_sample_progress", None)
        if callback is not None:
            current = await self._repo.get_run(run.id)
            if current is not None:
                callback(
                    run_id=run.id,
                    sample_id=sample.id,
                    sample_code=sample.sample_code,
                    status=BenchmarkCaseStatus.EXEC_ERROR.value,
                    processed_count=int(current.processed_count or 0),
                    total_count=int(current.total_count or 0),
                    success_count=int(current.success_count or 0),
                    failed_count=int(current.failed_count or 0),
                    elapsed_ms=0,
                )

    async def _run_sample(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
    ) -> dict[str, Any]:
        started_at = datetime.now().astimezone()
        t0 = time.perf_counter()
        generated_sql: str | None = None
        detail: dict[str, Any] = {}
        metric_values: dict[str, float] = {}
        method_result: _MethodRunResult | None = None
        status = BenchmarkCaseStatus.SUCCESS.value
        error_message: str | None = None
        generated_exec: _SqlExecution | None = None
        gold_exec: _SqlExecution | None = None
        generated_sql_error: str | None = None
        gold_sql_error: str | None = None
        question = build_benchmark_question(
            sample.question,
            sample.evidence,
            evidence_enabled=_snapshot_bool(
                run.method_config_snapshot,
                "evidence_enabled",
                "evidenceEnabled",
                default=False,
            ),
        )
        try:
            method_result = await asyncio.wait_for(
                self._run_method(run, sample, question),
                timeout=run.timeout_seconds,
            )
            generated_sql = method_result.generated_sql
            if not generated_sql:
                raise ChatbiBenchmarkServiceError.bad_request("被测方法未生成 SQL")
        except TimeoutError:
            status = BenchmarkCaseStatus.TIMEOUT.value
            error_message = "问数链路执行超时"
        except ChatbiDatasourceServiceError as exc:
            status = BenchmarkCaseStatus.EXEC_ERROR.value
            error_message = exc.message
        except Exception as exc:
            status = BenchmarkCaseStatus.EXEC_ERROR.value
            error_message = str(exc)

        if status == BenchmarkCaseStatus.SUCCESS.value and generated_sql:
            generated_exec, generated_sql_error = await self._execute_sql_safe(
                datasource_id=sample.datasource_id,
                sql=generated_sql,
                timeout_seconds=run.timeout_seconds,
            )
            if generated_sql_error:
                status = BenchmarkCaseStatus.EXEC_ERROR.value
                error_message = f"Generated SQL 执行失败: {generated_sql_error}"
            else:
                gold_exec, gold_sql_error = await self._execute_sql_safe(
                    datasource_id=sample.datasource_id,
                    sql=sample.gold_sql,
                    timeout_seconds=run.timeout_seconds,
                )
                if gold_sql_error:
                    status = BenchmarkCaseStatus.EXEC_ERROR.value
                    error_message = f"Gold SQL 执行失败: {gold_sql_error}"
                else:
                    datasource = await self._ds_repo.get_by_id(sample.datasource_id)
                    dialect = connector_type_to_dialect(
                        datasource.connector_type if datasource else None
                    )
                    metric_values, detail = compute_benchmark_metrics(
                        gold_sql=sample.gold_sql,
                        generated_sql=generated_sql,
                        ref_json=sample.ref_json,
                        gold_rows=gold_exec.rows if gold_exec else [],
                        generated_rows=generated_exec.rows if generated_exec else [],
                        db_schema=datasource.db_schema if datasource else None,
                        dialect=dialect,
                    )
        finished_at = datetime.now().astimezone()
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        total_tokens = _case_total_tokens(method_result.token_usage if method_result else {})
        detail.update(
            {
                "query_stream_events": (method_result.query_stream_events if method_result else []),
                "qsql_recall": _qsql_recall_detail(
                    method_result.query_stream_events if method_result else []
                ),
                "stage_latency_ms": (method_result.stage_latency_ms if method_result else {}),
                "token_usage": (method_result.token_usage if method_result else {}),
                "raw_output": (method_result.raw_output if method_result else {}),
                "sql_execution": _benchmark_sql_execution_detail(
                    generated_exec=generated_exec,
                    gold_exec=gold_exec,
                    generated_error=generated_sql_error,
                    gold_error=gold_sql_error,
                ),
                "error": {"message": error_message} if error_message else {},
            }
        )
        return {
            "run_id": run.id,
            "sample_id": sample.id,
            "dataset_id": sample.dataset_id,
            "datasource_id": sample.datasource_id,
            "sample_code": sample.sample_code,
            "question_snapshot": question,
            "gold_sql_snapshot": sample.gold_sql,
            "generated_sql": generated_sql,
            "execution_accuracy": _decimal(metric_values.get("execution_accuracy")),
            "table_f1": _decimal(metric_values.get("table_f1")),
            "column_f1": _decimal(metric_values.get("column_f1")),
            "join_f1": _decimal(metric_values.get("join_f1")),
            "domain_knowledge_f1": _decimal(metric_values.get("domain_knowledge_f1")),
            "status": status,
            "error_message": error_message,
            "trace_id": method_result.trace_id if method_result else None,
            "detail_json": detail,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": total_tokens,
            "generated_sql_execute_ms": generated_exec.elapsed_ms if generated_exec else None,
            "gold_sql_execute_ms": gold_exec.elapsed_ms if gold_exec else None,
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_ms": elapsed_ms,
            "created_by": run.created_by,
            "updated_by": run.created_by,
        }

    async def _run_method(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
        question: str,
    ) -> _MethodRunResult:
        if run.method_type == BenchmarkMethodType.DIN_SQL.value:
            return await self._run_dinsql_method(run, sample, question)
        if run.method_type == BenchmarkMethodType.MULTI_AGENT.value:
            return await self._run_multi_agent_method(run, sample, question)
        if run.method_type == BenchmarkMethodType.SINGLE_AGENT.value:
            return await self._run_single_agent_method(run, sample, question)

        owner_id = await self._ds_repo.get_owner_id(sample.datasource_id)
        if owner_id is None:
            raise ChatbiBenchmarkServiceError.bad_request("样本数据源不存在")
        query_service = ChatbiQueryService(
            unit_of_work=self._uow,
            redis=self._redis,
            llm_service=self._llm,
            rewrite_service=self._rewrite,
        )
        generated_sql: str | None = None
        query_stream_events: list[dict[str, Any]] = []
        token_usage: dict[str, int | None] = {}
        async for event in query_service.run_query_stream(
            ChatbiQueryRunInput(
                user_id=owner_id,
                question=question,
                datasource_id=sample.datasource_id,
                options=_options_from_snapshot(run.method_config_snapshot),
            )
        ):
            query_stream_events.append(_benchmark_stream_event_payload(event))
            if event.event == CHATBI_SSE_SQL and event.sql:
                generated_sql = event.sql
            if event.event == CHATBI_SSE_COMPLETED:
                token_usage = _token_usage_from_stream_event(event)
        if not token_usage:
            for payload in reversed(query_stream_events):
                token_usage = _token_usage_from_stream_payload(payload)
                if token_usage:
                    break
        return _MethodRunResult(
            generated_sql=generated_sql,
            trace_id=None,
            stage_latency_ms={},
            token_usage=token_usage,
            query_stream_events=query_stream_events,
            raw_output={},
        )

    async def _run_dinsql_method(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
        question: str,
    ) -> _MethodRunResult:
        datasource = await self._ds_repo.get_by_id(sample.datasource_id)
        if datasource is None:
            raise ChatbiBenchmarkServiceError.bad_request("sample datasource not found")
        generated_sql: str | None = None
        query_stream_events: list[dict[str, Any]] = []
        token_usage: dict[str, int | None] = {}
        runner = DinSqlRunner(llm_service=self._llm)
        async for event in runner.run_stream(
            question=question,
            datasource=datasource,
            model=_model_from_snapshot(run.method_config_snapshot),
        ):
            query_stream_events.append(_benchmark_stream_event_payload(event))
            if event.event == CHATBI_SSE_SQL and event.sql:
                generated_sql = event.sql
            if event.event == CHATBI_SSE_COMPLETED:
                if event.total_tokens is not None:
                    token_usage = {"total_tokens": event.total_tokens}
        return _MethodRunResult(
            generated_sql=generated_sql,
            trace_id=None,
            stage_latency_ms={},
            token_usage=token_usage,
            query_stream_events=query_stream_events,
            raw_output={"query_stream_events": query_stream_events},
        )


    async def _run_multi_agent_method(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
        question: str,
    ) -> _MethodRunResult:
        datasource = await self._ds_repo.get_by_id(sample.datasource_id)
        if datasource is None:
            raise ChatbiBenchmarkServiceError.bad_request("sample datasource not found")
        owner_id = await self._ds_repo.get_owner_id(sample.datasource_id)
        runner = MultiAgentSqlRunner(llm_service=self._llm, db_connection=self._db_conn)
        result = await runner.run(
            question=question,
            datasource=datasource,
            datasource_owner_id=owner_id,
            model=_model_from_snapshot(run.method_config_snapshot),
        )
        return _MethodRunResult(
            generated_sql=result.sql,
            trace_id=None,
            stage_latency_ms={},
            token_usage=result.token_usage,
            query_stream_events=result.query_stream_events,
            raw_output=result.raw_output,
        )


    async def _run_single_agent_method(
        self,
        run: BenchmarkRunRecord,
        sample: BenchmarkSampleRecord,
        question: str,
    ) -> _MethodRunResult:
        datasource = await self._ds_repo.get_by_id(sample.datasource_id)
        if datasource is None:
            raise ChatbiBenchmarkServiceError.bad_request("sample datasource not found")
        owner_id = await self._ds_repo.get_owner_id(sample.datasource_id)
        runner = SingleAgentSqlRunner(
            llm_service=self._llm,
            db_connection=self._db_conn,
            timeout=run.timeout_seconds,
        )
        result = await runner.run(
            question,
            datasource,
            owner_id,
            _model_from_snapshot(run.method_config_snapshot),
        )
        return _MethodRunResult(
            generated_sql=result.sql,
            trace_id=None,
            stage_latency_ms={},
            token_usage=result.token_usage,
            query_stream_events=result.query_stream_events,
            raw_output=result.raw_output,
        )

    async def _execute_sql_safe(
        self,
        *,
        datasource_id: int,
        sql: str,
        timeout_seconds: int,
    ) -> tuple[_SqlExecution | None, str | None]:
        try:
            return (
                await self._execute_sql(
                    datasource_id=datasource_id,
                    sql=sql,
                    timeout_seconds=timeout_seconds,
                ),
                None,
            )
        except TimeoutError:
            return None, "执行超时"
        except ChatbiDatasourceServiceError as exc:
            return None, exc.message
        except Exception as exc:
            return None, str(exc)[:2000]

    async def _execute_sql(
        self,
        *,
        datasource_id: int,
        sql: str,
        timeout_seconds: int,
    ) -> _SqlExecution:
        t0 = time.perf_counter()
        columns, rows, truncated = await asyncio.wait_for(
            self._db_conn.execute_readonly_sql_by_datasource(
                datasource_id=datasource_id,
                sql=sql,
                timeout_seconds=timeout_seconds,
            ),
            timeout=timeout_seconds,
        )
        return _SqlExecution(
            columns=columns,
            rows=rows,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            truncated=truncated,
        )

    async def _write_metric_summaries(self, run: BenchmarkRunRecord) -> None:
        cases = await self._repo.list_cases_for_run(run.id)
        total = len(cases)
        if total == 0:
            return
        summaries = _build_summaries(cases)
        await self._repo.replace_metric_summaries(run.id, summaries, user_id=run.created_by)

    async def _load_ready_dataset(self, dataset_id: int) -> BenchmarkDatasetRecord:
        dataset = await self._repo.get_dataset(dataset_id)
        if dataset is None or not dataset.is_enabled:
            raise ChatbiBenchmarkServiceError.not_found("数据集不存在")
        if dataset.status != BenchmarkDatasetStatus.READY.value:
            raise ChatbiBenchmarkServiceError.status_invalid("数据集未就绪")
        return dataset

    async def _validate_run_scope(self, payload: BenchmarkRunCreateInput) -> None:
        links = await self._repo.list_dataset_datasources(payload.dataset_id)
        ready_ids = {
            item.datasource_id
            for item in links
            if item.status == BenchmarkDatasourceStatus.READY.value
        }
        if not ready_ids:
            raise ChatbiBenchmarkServiceError.status_invalid("数据集数据源未就绪")
        if payload.selected_datasource_ids:
            invalid = set(payload.selected_datasource_ids) - ready_ids
            if invalid:
                raise ChatbiBenchmarkServiceError.bad_request(
                    "selectedDatasourceIds 不属于当前数据集"
                )
        if payload.source_group:
            groups = await self._repo.list_source_groups(payload.dataset_id)
            if payload.source_group not in groups:
                raise ChatbiBenchmarkServiceError.bad_request("sourceGroup 不属于当前数据集")

    async def _publish_run(self, run_id: int) -> None:
        await self._publisher.publish(
            StreamPayload(
                task_type=CHATBI_BENCHMARK_STREAM_TASK_TYPE,
                payload={"run_id": run_id},
            )
        )

    async def _publish_rerun(self, run_id: int, result_id: int) -> None:
        await self._publisher.publish(
            StreamPayload(
                task_type=CHATBI_BENCHMARK_STREAM_TASK_TYPE,
                payload={
                    "run_id": run_id,
                    "result_id": result_id,
                    "task_action": CHATBI_BENCHMARK_TASK_ACTION_RERUN_CASE,
                },
            )
        )

    async def _commit(self) -> None:
        try:
            await self._uow.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ChatbiBenchmarkServiceError.bad_request("评价数据完整性约束冲突") from exc


def _model_from_snapshot(snapshot: dict[str, Any]) -> str | None:
    model_value = _snapshot_value(snapshot, "model", "model", default="default")
    if isinstance(model_value, str) and model_value.strip() and model_value.strip() != "default":
        return model_value.strip()
    return None


def _options_from_snapshot(snapshot: dict[str, Any]) -> ChatbiQueryRunOptions:
    model_value = _snapshot_value(snapshot, "model", "model", default="default")
    completion_model = None
    if isinstance(model_value, str) and model_value.strip() and model_value.strip() != "default":
        completion_model = model_value.strip()
    schema_top_k_raw = _snapshot_value(snapshot, "schema_top_k", "schemaTopK", default=None)
    schema_top_k = int(schema_top_k_raw) if schema_top_k_raw is not None else None
    fix_max_raw = _snapshot_value(snapshot, "sql_fix_max_attempts", "sqlFixMaxAttempts", default=None)
    sql_fix_max_attempts = int(fix_max_raw) if fix_max_raw is not None else None
    return ChatbiQueryRunOptions(
        schema_selection_enabled=_snapshot_bool(
            snapshot,
            "schema_selection_enabled",
            "schemaSelectionEnabled",
            default=True,
        ),
        qsql_recall_enabled=_snapshot_bool(
            snapshot,
            "qsql_recall_enabled",
            "qsqlRecallEnabled",
            default=True,
        ),
        business_knowledge_recall_enabled=bool(
            _snapshot_bool(
                snapshot,
                "business_knowledge_recall_enabled",
                "businessKnowledgeRecallEnabled",
                default=True,
            )
        ),
        sql_fix_enabled=_snapshot_bool(
            snapshot,
            "sql_fix_enabled",
            "sqlFixEnabled",
            default=True,
        ),
        rewrite_enabled=_snapshot_bool(
            snapshot,
            "rewrite_enabled",
            "rewriteEnabled",
            default=True,
        ),
        summary_enabled=_snapshot_bool(
            snapshot,
            "summary_enabled",
            "summaryEnabled",
            default=True,
        ),
        sql_candidate_paths=_snapshot_value(
            snapshot,
            "sql_candidate_paths",
            "sqlCandidatePaths",
            default=["ddl:chain_of_thought"],
        ),
        sql_selection_enabled=_snapshot_bool(
            snapshot,
            "sql_selection_enabled",
            "sqlSelectionEnabled",
            default=True,
        ),
        sql_validate_enabled=_snapshot_bool(
            snapshot,
            "sql_validate_enabled",
            "sqlValidateEnabled",
            default=True,
        ),
        schema_top_k=schema_top_k,
        schema_full_if_small=_snapshot_bool(
            snapshot,
            "schema_full_if_small",
            "schemaFullIfSmall",
            default=False,
        ),
        schema_small_table_threshold=int(
            _snapshot_value(
                snapshot,
                "schema_small_table_threshold",
                "schemaSmallTableThreshold",
                default=15,
            )
            or 15
        ),
        completion_model=completion_model,
        sql_fix_max_attempts=sql_fix_max_attempts,
        clarification_enabled=False,
        intent_enabled=False,
        rag_enabled=_snapshot_bool(
            snapshot,
            "rag_enabled",
            "ragEnabled",
            default=False,
        ),
        value_founding_enabled=_snapshot_bool(
            snapshot,
            "value_founding_enabled",
            "valueFoundingEnabled",
            default=True,
        ),
        value_search_enabled=_snapshot_bool(
            snapshot,
            "value_search_enabled",
            "valueSearchEnabled",
            default=False,
        ),
        group_by_audit_enabled=_snapshot_bool(
            snapshot,
            "group_by_audit_enabled",
            "groupByAuditEnabled",
            default=False,
        ),
    )


def _snapshot_value(
    snapshot: dict[str, Any],
    key: str,
    legacy_key: str,
    *,
    default: Any,
) -> Any:
    if key in snapshot:
        return snapshot.get(key)
    if legacy_key in snapshot:
        return snapshot.get(legacy_key)
    return default


def _snapshot_bool(
    snapshot: dict[str, Any],
    key: str,
    legacy_key: str,
    *,
    default: bool,
) -> bool:
    if key in snapshot:
        return bool(snapshot[key])
    if legacy_key in snapshot:
        return bool(snapshot[legacy_key])
    return default


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _build_summaries(cases: list[BenchmarkCaseResultRecord]) -> list[dict[str, Any]]:
    active_cases = [case for case in cases if case.status != BenchmarkCaseStatus.RERUNNING.value]
    total = len(active_cases)
    if total == 0:
        return []
    success_cases = [
        case for case in active_cases if case.status == BenchmarkCaseStatus.SUCCESS.value
    ]
    metric_pairs = [
        (BenchmarkMetricName.EXECUTION_ACCURACY.value, "execution_accuracy"),
        (BenchmarkMetricName.TABLE_F1.value, "table_f1"),
        (BenchmarkMetricName.COLUMN_F1.value, "column_f1"),
        (BenchmarkMetricName.JOIN_F1.value, "join_f1"),
        (BenchmarkMetricName.DOMAIN_KNOWLEDGE_F1.value, "domain_knowledge_f1"),
    ]
    out: list[dict[str, Any]] = []
    for metric_name, attr in metric_pairs:
        values = [
            float(getattr(case, attr)) for case in success_cases if getattr(case, attr) is not None
        ]
        out.append(_summary(metric_name, _avg(values), len(values)))
    out.extend(
        [
            _summary(BenchmarkMetricName.VALID_SQL_RATE.value, len(success_cases) / total, total),
            _summary(
                BenchmarkMetricName.EXECUTION_ERROR_RATE.value,
                len([c for c in active_cases if c.status == BenchmarkCaseStatus.EXEC_ERROR.value])
                / total,
                total,
            ),
            _summary(
                BenchmarkMetricName.TIMEOUT_RATE.value,
                len([c for c in active_cases if c.status == BenchmarkCaseStatus.TIMEOUT.value])
                / total,
                total,
            ),
            _summary(
                BenchmarkMetricName.AVG_ELAPSED_MS.value,
                _avg([float(c.elapsed_ms) for c in active_cases if c.elapsed_ms is not None]),
                total,
            ),
            _summary(
                BenchmarkMetricName.AVG_GENERATED_SQL_EXECUTE_MS.value,
                _avg(
                    [
                        float(c.generated_sql_execute_ms)
                        for c in active_cases
                        if c.generated_sql_execute_ms is not None
                    ]
                ),
                total,
            ),
            _summary(
                BenchmarkMetricName.AVG_GOLD_SQL_EXECUTE_MS.value,
                _avg(
                    [
                        float(c.gold_sql_execute_ms)
                        for c in active_cases
                        if c.gold_sql_execute_ms is not None
                    ]
                ),
                total,
            ),
            _summary(
                BenchmarkMetricName.AVG_TOTAL_TOKENS.value,
                _avg([float(c.total_tokens) for c in active_cases if c.total_tokens is not None]),
                total,
            ),
        ]
    )
    return out


def _summary(metric_name: str, value: float, sample_count: int) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "metric_value": round(float(value), 6),
        "sample_count": sample_count,
        "extra_json": {},
    }


def _benchmark_stream_event_payload(event: ChatbiQueryStreamEvent) -> dict[str, Any]:
    """持久化 benchmark 样本问数 SSE 事件；data 行数过大时截断。"""
    payload = serialize_chatbi_stream_event(event)
    if payload.get("event") != CHATBI_SSE_DATA:
        return payload
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) <= _BENCHMARK_SSE_DATA_PREVIEW_ROWS:
        return payload
    preview = dict(payload)
    preview["rows"] = rows[:_BENCHMARK_SSE_DATA_PREVIEW_ROWS]
    preview["previewRowCount"] = len(rows[:_BENCHMARK_SSE_DATA_PREVIEW_ROWS])
    preview["totalRowCount"] = len(rows)
    preview["rowsTruncatedForStorage"] = True
    return preview


__all__ = [
    "CHATBI_BENCHMARK_STREAM_TASK_TYPE",
    "CHATBI_BENCHMARK_TASK_STREAM",
    "ChatbiBenchmarkService",
    "ChatbiBenchmarkServiceError",
    "build_benchmark_question",
    "build_reference_json",
]
