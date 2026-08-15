"""ChatBI 基准评价数据访问。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....domain.system.chatbi.benchmark import (
    BenchmarkCaseListParams,
    BenchmarkCaseResultRecord,
    BenchmarkCaseStatus,
    BenchmarkDatasetDatasourceRecord,
    BenchmarkDatasetRecord,
    BenchmarkDatasetStatus,
    BenchmarkMetricSummaryRecord,
    BenchmarkRunListParams,
    BenchmarkRunRecord,
    BenchmarkRunStatus,
    BenchmarkSampleRecord,
)
from ....models.system.chatbi.benchmark import (
    ChatbiBenchmarkCaseResult,
    ChatbiBenchmarkDataset,
    ChatbiBenchmarkDatasetDatasource,
    ChatbiBenchmarkMetricSummary,
    ChatbiBenchmarkRun,
    ChatbiBenchmarkSample,
)
from .mapping import require_datetime


def _result_rowcount(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _to_dataset_record(entity: ChatbiBenchmarkDataset) -> BenchmarkDatasetRecord:
    return BenchmarkDatasetRecord(
        id=int(entity.id),
        dataset_code=entity.dataset_code,
        display_name=entity.display_name,
        description=entity.description,
        current_version=entity.current_version,
        sample_count=int(entity.sample_count),
        datasource_count=int(entity.datasource_count),
        status=entity.status,
        is_enabled=bool(entity.is_enabled),
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


def _to_dataset_datasource_record(
    entity: ChatbiBenchmarkDatasetDatasource,
) -> BenchmarkDatasetDatasourceRecord:
    return BenchmarkDatasetDatasourceRecord(
        id=int(entity.id),
        dataset_id=int(entity.dataset_id),
        datasource_id=int(entity.datasource_id),
        db_id=entity.db_id,
        display_name=entity.display_name,
        status=entity.status,
        sample_count=int(entity.sample_count),
        sort_order=int(entity.sort_order),
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


def _to_sample_record(entity: ChatbiBenchmarkSample) -> BenchmarkSampleRecord:
    return BenchmarkSampleRecord(
        id=int(entity.id),
        sample_code=entity.sample_code,
        dataset_id=int(entity.dataset_id),
        dataset_version=entity.dataset_version,
        datasource_id=int(entity.datasource_id),
        db_id=entity.db_id,
        source_group=entity.source_group,
        question=entity.question,
        gold_sql=entity.gold_sql,
        evidence=entity.evidence,
        ref_json=dict(entity.ref_json or {}),
        is_enabled=bool(entity.is_enabled),
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


def _to_run_record(entity: ChatbiBenchmarkRun) -> BenchmarkRunRecord:
    selected_ids = entity.selected_datasource_ids
    return BenchmarkRunRecord(
        id=int(entity.id),
        dataset_id=int(entity.dataset_id),
        dataset_code=entity.dataset_code,
        dataset_version=entity.dataset_version,
        method_type=entity.method_type,
        method_config_snapshot=dict(entity.method_config_snapshot or {}),
        selected_datasource_ids=list(selected_ids) if isinstance(selected_ids, list) else None,
        source_group=entity.source_group,
        sample_limit=entity.sample_limit,
        concurrency=int(entity.concurrency),
        timeout_seconds=int(entity.timeout_seconds),
        status=entity.status,
        total_count=int(entity.total_count),
        processed_count=int(entity.processed_count),
        success_count=int(entity.success_count),
        failed_count=int(entity.failed_count),
        last_error=entity.last_error,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        created_by=entity.created_by,
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


def _to_case_record(entity: ChatbiBenchmarkCaseResult) -> BenchmarkCaseResultRecord:
    return BenchmarkCaseResultRecord(
        id=int(entity.id),
        run_id=int(entity.run_id),
        sample_id=int(entity.sample_id),
        dataset_id=int(entity.dataset_id),
        datasource_id=int(entity.datasource_id),
        sample_code=entity.sample_code,
        question_snapshot=entity.question_snapshot,
        gold_sql_snapshot=entity.gold_sql_snapshot,
        generated_sql=entity.generated_sql,
        execution_accuracy=_float_or_none(entity.execution_accuracy),
        table_f1=_float_or_none(entity.table_f1),
        column_f1=_float_or_none(entity.column_f1),
        join_f1=_float_or_none(entity.join_f1),
        domain_knowledge_f1=_float_or_none(entity.domain_knowledge_f1),
        status=entity.status,
        error_message=entity.error_message,
        trace_id=entity.trace_id,
        detail_json=dict(entity.detail_json or {}),
        prompt_tokens=entity.prompt_tokens,
        completion_tokens=entity.completion_tokens,
        total_tokens=entity.total_tokens,
        generated_sql_execute_ms=entity.generated_sql_execute_ms,
        gold_sql_execute_ms=entity.gold_sql_execute_ms,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        elapsed_ms=entity.elapsed_ms,
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


def _to_metric_record(entity: ChatbiBenchmarkMetricSummary) -> BenchmarkMetricSummaryRecord:
    return BenchmarkMetricSummaryRecord(
        id=int(entity.id),
        run_id=int(entity.run_id),
        metric_name=entity.metric_name,
        metric_value=float(entity.metric_value),
        sample_count=int(entity.sample_count),
        extra_json=dict(entity.extra_json or {}),
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


class ChatbiBenchmarkRepository:
    """封装 ChatBI benchmark 表读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_datasets(self) -> list[BenchmarkDatasetRecord]:
        stmt = (
            select(ChatbiBenchmarkDataset)
            .where(
                ChatbiBenchmarkDataset.is_deleted.is_(False),
                ChatbiBenchmarkDataset.is_enabled.is_(True),
            )
            .order_by(ChatbiBenchmarkDataset.updated_at.desc(), ChatbiBenchmarkDataset.id.desc())
        )
        rows = await self._session.execute(stmt)
        return [_to_dataset_record(entity) for entity in rows.scalars().all()]

    async def get_dataset(self, dataset_id: int) -> BenchmarkDatasetRecord | None:
        stmt = select(ChatbiBenchmarkDataset).where(
            ChatbiBenchmarkDataset.id == dataset_id,
            ChatbiBenchmarkDataset.is_deleted.is_(False),
        )
        entity = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_dataset_record(entity) if entity is not None else None

    async def get_dataset_by_code(self, dataset_code: str) -> BenchmarkDatasetRecord | None:
        stmt = select(ChatbiBenchmarkDataset).where(
            ChatbiBenchmarkDataset.dataset_code == dataset_code,
            ChatbiBenchmarkDataset.is_deleted.is_(False),
        )
        entity = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_dataset_record(entity) if entity is not None else None

    async def upsert_dataset(
        self,
        *,
        dataset_code: str,
        display_name: str,
        description: str | None,
        current_version: str,
        user_id: int,
    ) -> int:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkDataset).where(
                    ChatbiBenchmarkDataset.dataset_code == dataset_code,
                    ChatbiBenchmarkDataset.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            entity = ChatbiBenchmarkDataset(
                dataset_code=dataset_code,
                display_name=display_name,
                description=description,
                current_version=current_version,
                sample_count=0,
                datasource_count=0,
                status=BenchmarkDatasetStatus.NOT_READY.value,
                is_enabled=True,
                created_by=user_id,
                updated_by=user_id,
            )
            self._session.add(entity)
        else:
            entity.display_name = display_name
            entity.description = description
            entity.current_version = current_version
            entity.updated_by = user_id
        await self._session.flush()
        return int(entity.id)

    async def list_dataset_datasources(
        self,
        dataset_id: int,
    ) -> list[BenchmarkDatasetDatasourceRecord]:
        stmt = (
            select(ChatbiBenchmarkDatasetDatasource)
            .where(
                ChatbiBenchmarkDatasetDatasource.dataset_id == dataset_id,
                ChatbiBenchmarkDatasetDatasource.is_deleted.is_(False),
            )
            .order_by(
                ChatbiBenchmarkDatasetDatasource.sort_order.asc(),
                ChatbiBenchmarkDatasetDatasource.id.asc(),
            )
        )
        rows = await self._session.execute(stmt)
        return [_to_dataset_datasource_record(entity) for entity in rows.scalars().all()]

    async def get_datasource_qsql_scope_filter(
        self,
        datasource_id: int,
    ) -> tuple[str, str] | None:
        """若数据源已关联 benchmark，返回 (dataset_code, db_id) 供 GLOBAL Q-SQL 过滤。"""
        stmt = (
            select(
                ChatbiBenchmarkDataset.dataset_code,
                ChatbiBenchmarkDatasetDatasource.db_id,
            )
            .join(
                ChatbiBenchmarkDataset,
                ChatbiBenchmarkDataset.id == ChatbiBenchmarkDatasetDatasource.dataset_id,
            )
            .where(
                ChatbiBenchmarkDatasetDatasource.datasource_id == datasource_id,
                ChatbiBenchmarkDatasetDatasource.is_deleted.is_(False),
                ChatbiBenchmarkDataset.is_deleted.is_(False),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        dataset_code = str(row[0] or "").strip()
        db_id = str(row[1] or "").strip()
        if not dataset_code or not db_id:
            return None
        return dataset_code, db_id

    async def upsert_dataset_datasource(
        self,
        *,
        dataset_id: int,
        datasource_id: int,
        db_id: str,
        display_name: str,
        status: str,
        sort_order: int,
        user_id: int,
    ) -> int:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkDatasetDatasource).where(
                    ChatbiBenchmarkDatasetDatasource.dataset_id == dataset_id,
                    ChatbiBenchmarkDatasetDatasource.datasource_id == datasource_id,
                    ChatbiBenchmarkDatasetDatasource.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            entity = ChatbiBenchmarkDatasetDatasource(
                dataset_id=dataset_id,
                datasource_id=datasource_id,
                db_id=db_id,
                display_name=display_name,
                status=status,
                sample_count=0,
                sort_order=sort_order,
                created_by=user_id,
                updated_by=user_id,
            )
            self._session.add(entity)
        else:
            entity.db_id = db_id
            entity.display_name = display_name
            entity.status = status
            entity.sort_order = sort_order
            entity.updated_by = user_id
        await self._session.flush()
        return int(entity.id)

    async def list_source_groups(self, dataset_id: int) -> list[str]:
        stmt = (
            select(ChatbiBenchmarkSample.source_group)
            .where(
                ChatbiBenchmarkSample.dataset_id == dataset_id,
                ChatbiBenchmarkSample.is_deleted.is_(False),
                ChatbiBenchmarkSample.is_enabled.is_(True),
            )
            .distinct()
            .order_by(ChatbiBenchmarkSample.source_group.asc())
        )
        rows = await self._session.execute(stmt)
        return [str(row[0]) for row in rows.all()]

    async def count_samples(
        self,
        *,
        dataset_id: int,
        selected_datasource_ids: list[int] | None,
        source_group: str | None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ChatbiBenchmarkSample)
            .where(
                ChatbiBenchmarkSample.dataset_id == dataset_id,
                ChatbiBenchmarkSample.is_deleted.is_(False),
                ChatbiBenchmarkSample.is_enabled.is_(True),
            )
        )
        if selected_datasource_ids:
            stmt = stmt.where(ChatbiBenchmarkSample.datasource_id.in_(selected_datasource_ids))
        if source_group:
            stmt = stmt.where(ChatbiBenchmarkSample.source_group == source_group)
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def list_samples_for_run(
        self,
        *,
        dataset_id: int,
        selected_datasource_ids: list[int] | None,
        source_group: str | None,
        limit: int | None,
        sample_ids: list[int] | None = None,
    ) -> list[BenchmarkSampleRecord]:
        stmt = (
            select(ChatbiBenchmarkSample)
            .where(
                ChatbiBenchmarkSample.dataset_id == dataset_id,
                ChatbiBenchmarkSample.is_deleted.is_(False),
                ChatbiBenchmarkSample.is_enabled.is_(True),
            )
            .order_by(ChatbiBenchmarkSample.id.asc())
        )
        if selected_datasource_ids:
            stmt = stmt.where(ChatbiBenchmarkSample.datasource_id.in_(selected_datasource_ids))
        if source_group:
            stmt = stmt.where(ChatbiBenchmarkSample.source_group == source_group)
        if sample_ids:
            stmt = stmt.where(ChatbiBenchmarkSample.id.in_(sample_ids))
        stmt = stmt.order_by(ChatbiBenchmarkSample.id.asc())
        if limit is not None and not sample_ids:
            stmt = stmt.limit(limit)
        rows = await self._session.execute(stmt)
        records = [_to_sample_record(entity) for entity in rows.scalars().all()]
        if sample_ids:
            order = {sample_id: index for index, sample_id in enumerate(sample_ids)}
            records.sort(key=lambda item: order.get(item.id, len(order)))
        return records

    async def upsert_sample(
        self,
        *,
        sample_code: str,
        dataset_id: int,
        dataset_version: str,
        datasource_id: int,
        db_id: str,
        source_group: str,
        question: str,
        gold_sql: str,
        evidence: str | None,
        ref_json: dict[str, Any],
        user_id: int,
    ) -> int:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkSample).where(
                    ChatbiBenchmarkSample.dataset_id == dataset_id,
                    ChatbiBenchmarkSample.dataset_version == dataset_version,
                    ChatbiBenchmarkSample.sample_code == sample_code,
                    ChatbiBenchmarkSample.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            entity = ChatbiBenchmarkSample(
                sample_code=sample_code,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                datasource_id=datasource_id,
                db_id=db_id,
                source_group=source_group,
                question=question,
                gold_sql=gold_sql,
                evidence=evidence,
                ref_json=dict(ref_json),
                is_enabled=True,
                created_by=user_id,
                updated_by=user_id,
            )
            self._session.add(entity)
        else:
            entity.datasource_id = datasource_id
            entity.db_id = db_id
            entity.source_group = source_group
            entity.question = question
            entity.gold_sql = gold_sql
            entity.evidence = evidence
            entity.ref_json = dict(ref_json)
            entity.is_enabled = True
            entity.updated_by = user_id
        await self._session.flush()
        return int(entity.id)

    async def refresh_dataset_counts(self, dataset_id: int, *, user_id: int) -> None:
        sample_count = await self.count_samples(
            dataset_id=dataset_id,
            selected_datasource_ids=None,
            source_group=None,
        )
        datasource_count = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(ChatbiBenchmarkDatasetDatasource)
                    .where(
                        ChatbiBenchmarkDatasetDatasource.dataset_id == dataset_id,
                        ChatbiBenchmarkDatasetDatasource.is_deleted.is_(False),
                    )
                )
            ).scalar_one()
            or 0
        )
        await self._session.execute(
            update(ChatbiBenchmarkDataset)
            .where(ChatbiBenchmarkDataset.id == dataset_id)
            .values(
                sample_count=sample_count,
                datasource_count=datasource_count,
                status=(
                    BenchmarkDatasetStatus.READY.value
                    if sample_count > 0 and datasource_count > 0
                    else BenchmarkDatasetStatus.NOT_READY.value
                ),
                updated_by=user_id,
                updated_at=datetime.now().astimezone(),
            )
        )

    async def refresh_dataset_datasource_counts(self, dataset_id: int) -> None:
        links = await self.list_dataset_datasources(dataset_id)
        for link in links:
            count = await self.count_samples(
                dataset_id=dataset_id,
                selected_datasource_ids=[link.datasource_id],
                source_group=None,
            )
            await self._session.execute(
                update(ChatbiBenchmarkDatasetDatasource)
                .where(ChatbiBenchmarkDatasetDatasource.id == link.id)
                .values(sample_count=count, updated_at=datetime.now().astimezone())
            )

    async def create_run(
        self,
        *,
        dataset: BenchmarkDatasetRecord,
        method_type: str,
        method_config_snapshot: dict[str, Any],
        selected_datasource_ids: list[int] | None,
        source_group: str | None,
        sample_limit: int | None,
        concurrency: int,
        timeout_seconds: int,
        total_count: int,
        user_id: int,
    ) -> int:
        entity = ChatbiBenchmarkRun(
            dataset_id=dataset.id,
            dataset_code=dataset.dataset_code,
            dataset_version=dataset.current_version,
            method_type=method_type,
            method_config_snapshot=dict(method_config_snapshot),
            selected_datasource_ids=(
                list(selected_datasource_ids) if selected_datasource_ids else None
            ),
            source_group=source_group,
            sample_limit=sample_limit,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
            status=BenchmarkRunStatus.PENDING.value,
            total_count=total_count,
            processed_count=0,
            success_count=0,
            failed_count=0,
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def get_run(self, run_id: int) -> BenchmarkRunRecord | None:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkRun).where(
                    ChatbiBenchmarkRun.id == run_id,
                    ChatbiBenchmarkRun.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        return _to_run_record(entity) if entity is not None else None

    async def get_run_for_user(self, run_id: int, user_id: int) -> BenchmarkRunRecord | None:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkRun).where(
                    ChatbiBenchmarkRun.id == run_id,
                    ChatbiBenchmarkRun.created_by == user_id,
                    ChatbiBenchmarkRun.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        return _to_run_record(entity) if entity is not None else None

    async def list_runs(
        self,
        params: BenchmarkRunListParams,
    ) -> tuple[list[BenchmarkRunRecord], int]:
        filters = [
            ChatbiBenchmarkRun.created_by == params.user_id,
            ChatbiBenchmarkRun.is_deleted.is_(False),
        ]
        if params.dataset_id is not None:
            filters.append(ChatbiBenchmarkRun.dataset_id == params.dataset_id)
        if params.status:
            filters.append(ChatbiBenchmarkRun.status == params.status)
        base = select(ChatbiBenchmarkRun).where(*filters)
        total = int(
            (
                await self._session.execute(select(func.count()).select_from(base.subquery()))
            ).scalar_one()
            or 0
        )
        stmt = (
            base.order_by(ChatbiBenchmarkRun.created_at.desc(), ChatbiBenchmarkRun.id.desc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
        )
        rows = await self._session.execute(stmt)
        return [_to_run_record(entity) for entity in rows.scalars().all()], total

    async def mark_run_running(self, run_id: int) -> bool:
        now = datetime.now().astimezone()
        result = await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(
                ChatbiBenchmarkRun.id == run_id,
                ChatbiBenchmarkRun.status == BenchmarkRunStatus.PENDING.value,
                ChatbiBenchmarkRun.is_deleted.is_(False),
            )
            .values(status=BenchmarkRunStatus.RUNNING.value, started_at=now, updated_at=now)
        )
        return _result_rowcount(result) > 0

    async def cancel_run(self, run_id: int, user_id: int) -> bool:
        now = datetime.now().astimezone()
        result = await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(
                ChatbiBenchmarkRun.id == run_id,
                ChatbiBenchmarkRun.created_by == user_id,
                ChatbiBenchmarkRun.status.in_(
                    [BenchmarkRunStatus.PENDING.value, BenchmarkRunStatus.RUNNING.value]
                ),
                ChatbiBenchmarkRun.is_deleted.is_(False),
            )
            .values(
                status=BenchmarkRunStatus.CANCELED.value,
                finished_at=now,
                updated_by=user_id,
                updated_at=now,
            )
        )
        return _result_rowcount(result) > 0

    async def soft_delete_run(self, run_id: int, user_id: int) -> bool:
        """软删评价任务及其样本结果、汇总指标。"""
        run = await self.get_run_for_user(run_id, user_id)
        if run is None:
            return False
        if run.status in {
            BenchmarkRunStatus.PENDING.value,
            BenchmarkRunStatus.RUNNING.value,
        }:
            return False
        now = datetime.now().astimezone()
        await self._session.execute(
            update(ChatbiBenchmarkCaseResult)
            .where(
                ChatbiBenchmarkCaseResult.run_id == run_id,
                ChatbiBenchmarkCaseResult.is_deleted.is_(False),
            )
            .values(is_deleted=True, updated_by=user_id, updated_at=now)
        )
        await self._session.execute(
            update(ChatbiBenchmarkMetricSummary)
            .where(
                ChatbiBenchmarkMetricSummary.run_id == run_id,
                ChatbiBenchmarkMetricSummary.is_deleted.is_(False),
            )
            .values(is_deleted=True, updated_by=user_id, updated_at=now)
        )
        result = await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(
                ChatbiBenchmarkRun.id == run_id,
                ChatbiBenchmarkRun.created_by == user_id,
                ChatbiBenchmarkRun.is_deleted.is_(False),
            )
            .values(is_deleted=True, updated_by=user_id, updated_at=now)
        )
        return _result_rowcount(result) > 0

    async def recover_run(self, run_id: int, user_id: int) -> bool:
        """恢复中断的评价任务（断电等场景），重置为 PENDING 以便重新调度。"""
        run = await self.get_run_for_user(run_id, user_id)
        if run is None:
            return False
        if run.status != BenchmarkRunStatus.RUNNING.value:
            return False
        await self._session.execute(
            delete(ChatbiBenchmarkCaseResult).where(
                ChatbiBenchmarkCaseResult.run_id == run_id,
                ChatbiBenchmarkCaseResult.is_deleted.is_(False),
            )
        )
        await self._session.execute(
            delete(ChatbiBenchmarkMetricSummary).where(
                ChatbiBenchmarkMetricSummary.run_id == run_id,
                ChatbiBenchmarkMetricSummary.is_deleted.is_(False),
            )
        )
        now = datetime.now().astimezone()
        result = await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(
                ChatbiBenchmarkRun.id == run_id,
                ChatbiBenchmarkRun.created_by == user_id,
                ChatbiBenchmarkRun.is_deleted.is_(False),
            )
            .values(
                status=BenchmarkRunStatus.PENDING.value,
                processed_count=0,
                success_count=0,
                failed_count=0,
                last_error=None,
                started_at=None,
                finished_at=None,
                updated_by=user_id,
                updated_at=now,
            )
        )
        return _result_rowcount(result) > 0

    async def update_run_progress(
        self,
        run_id: int,
        *,
        success_delta: int,
        failed_delta: int,
        last_error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "processed_count": ChatbiBenchmarkRun.processed_count + 1,
            "success_count": ChatbiBenchmarkRun.success_count + success_delta,
            "failed_count": ChatbiBenchmarkRun.failed_count + failed_delta,
            "updated_at": datetime.now().astimezone(),
        }
        if last_error:
            values["last_error"] = last_error[:2000]
        await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(
                ChatbiBenchmarkRun.id == run_id,
                ChatbiBenchmarkRun.is_deleted.is_(False),
                ChatbiBenchmarkRun.status == BenchmarkRunStatus.RUNNING.value,
            )
            .values(**values)
        )

    async def finish_run(self, run_id: int, *, status: str, last_error: str | None = None) -> None:
        now = datetime.now().astimezone()
        await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(ChatbiBenchmarkRun.id == run_id)
            .values(status=status, last_error=last_error, finished_at=now, updated_at=now)
        )

    async def get_run_entity(self, run_id: int) -> ChatbiBenchmarkRun | None:
        return (
            await self._session.execute(
                select(ChatbiBenchmarkRun).where(
                    ChatbiBenchmarkRun.id == run_id,
                    ChatbiBenchmarkRun.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def get_sample(self, sample_id: int) -> BenchmarkSampleRecord | None:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkSample).where(
                    ChatbiBenchmarkSample.id == sample_id,
                    ChatbiBenchmarkSample.is_deleted.is_(False),
                    ChatbiBenchmarkSample.is_enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        return _to_sample_record(entity) if entity is not None else None

    async def create_case_result(self, **values: Any) -> int:
        entity = ChatbiBenchmarkCaseResult(**values)
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def update_case_result(self, result_id: int, **values: Any) -> bool:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkCaseResult).where(
                    ChatbiBenchmarkCaseResult.id == result_id,
                    ChatbiBenchmarkCaseResult.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            return False
        immutable = {"id", "run_id", "sample_id", "created_by", "created_at"}
        for key, value in values.items():
            if key in immutable:
                continue
            if hasattr(entity, key):
                setattr(entity, key, value)
        entity.updated_at = datetime.now().astimezone()
        await self._session.flush()
        return True

    async def adjust_run_case_counts(
        self,
        run_id: int,
        *,
        old_status: str,
        new_status: str,
        last_error: str | None = None,
        user_id: int | None,
    ) -> None:
        old_success = old_status == BenchmarkCaseStatus.SUCCESS.value
        new_success = new_status == BenchmarkCaseStatus.SUCCESS.value
        success_delta = (1 if new_success else 0) - (1 if old_success else 0)
        failed_delta = (0 if new_success else 1) - (0 if old_success else 1)
        run = await self.get_run_entity(run_id)
        if run is None:
            return
        run.success_count = max(0, int(run.success_count) + success_delta)
        run.failed_count = max(0, int(run.failed_count) + failed_delta)
        if last_error:
            run.last_error = last_error[:2000]
        run.updated_by = user_id
        run.updated_at = datetime.now().astimezone()
        await self._session.flush()

    async def list_cases(
        self,
        params: BenchmarkCaseListParams,
    ) -> tuple[list[BenchmarkCaseResultRecord], int]:
        filters = [
            ChatbiBenchmarkCaseResult.run_id == params.run_id,
            ChatbiBenchmarkCaseResult.is_deleted.is_(False),
        ]
        if params.status:
            filters.append(ChatbiBenchmarkCaseResult.status == params.status)
        base = select(ChatbiBenchmarkCaseResult).where(*filters)
        total = int(
            (
                await self._session.execute(select(func.count()).select_from(base.subquery()))
            ).scalar_one()
            or 0
        )
        stmt = (
            base.order_by(ChatbiBenchmarkCaseResult.id.asc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
        )
        rows = await self._session.execute(stmt)
        return [_to_case_record(entity) for entity in rows.scalars().all()], total

    async def get_case_result(
        self,
        *,
        run_id: int,
        result_id: int,
    ) -> BenchmarkCaseResultRecord | None:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkCaseResult).where(
                    ChatbiBenchmarkCaseResult.id == result_id,
                    ChatbiBenchmarkCaseResult.run_id == run_id,
                    ChatbiBenchmarkCaseResult.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        return _to_case_record(entity) if entity is not None else None

    async def mark_case_rerunning(self, result_id: int, *, user_id: int) -> bool:
        entity = (
            await self._session.execute(
                select(ChatbiBenchmarkCaseResult).where(
                    ChatbiBenchmarkCaseResult.id == result_id,
                    ChatbiBenchmarkCaseResult.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            return False
        if entity.status == BenchmarkCaseStatus.RERUNNING.value:
            return False
        detail = dict(entity.detail_json or {})
        detail["rerun"] = {"previous_status": entity.status}
        entity.status = BenchmarkCaseStatus.RERUNNING.value
        entity.detail_json = detail
        entity.updated_by = user_id
        entity.updated_at = datetime.now().astimezone()
        await self._session.flush()
        return True

    async def replace_metric_summaries(
        self,
        run_id: int,
        summaries: list[dict[str, Any]],
        *,
        user_id: int | None,
    ) -> None:
        existing = (
            (
                await self._session.execute(
                    select(ChatbiBenchmarkMetricSummary).where(
                        ChatbiBenchmarkMetricSummary.run_id == run_id,
                        ChatbiBenchmarkMetricSummary.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        for entity in existing:
            entity.is_deleted = True
            entity.updated_by = user_id
        for item in summaries:
            self._session.add(
                ChatbiBenchmarkMetricSummary(
                    run_id=run_id,
                    metric_name=str(item["metric_name"]),
                    metric_value=Decimal(str(item["metric_value"])),
                    sample_count=int(item["sample_count"]),
                    extra_json=dict(item.get("extra_json") or {}),
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
        await self._session.flush()

    async def list_metric_summaries(self, run_id: int) -> list[BenchmarkMetricSummaryRecord]:
        rows = await self._session.execute(
            select(ChatbiBenchmarkMetricSummary)
            .where(
                ChatbiBenchmarkMetricSummary.run_id == run_id,
                ChatbiBenchmarkMetricSummary.is_deleted.is_(False),
            )
            .order_by(ChatbiBenchmarkMetricSummary.id.asc())
        )
        return [_to_metric_record(entity) for entity in rows.scalars().all()]

    async def list_cases_for_run(self, run_id: int) -> list[BenchmarkCaseResultRecord]:
        rows = await self._session.execute(
            select(ChatbiBenchmarkCaseResult)
            .where(
                ChatbiBenchmarkCaseResult.run_id == run_id,
                ChatbiBenchmarkCaseResult.is_deleted.is_(False),
            )
            .order_by(ChatbiBenchmarkCaseResult.id.asc())
        )
        return [_to_case_record(entity) for entity in rows.scalars().all()]

    async def list_completed_sample_ids(self, run_id: int) -> set[int]:
        """已有终态结果的 sample_id（不含 RERUNNING）。"""
        rows = await self._session.execute(
            select(ChatbiBenchmarkCaseResult.sample_id).where(
                ChatbiBenchmarkCaseResult.run_id == run_id,
                ChatbiBenchmarkCaseResult.is_deleted.is_(False),
                ChatbiBenchmarkCaseResult.status != BenchmarkCaseStatus.RERUNNING.value,
            )
        )
        return {int(sample_id) for sample_id in rows.scalars().all()}

    async def soft_delete_rerunning_cases(self, run_id: int, *, user_id: int) -> int:
        now = datetime.now().astimezone()
        result = await self._session.execute(
            update(ChatbiBenchmarkCaseResult)
            .where(
                ChatbiBenchmarkCaseResult.run_id == run_id,
                ChatbiBenchmarkCaseResult.is_deleted.is_(False),
                ChatbiBenchmarkCaseResult.status == BenchmarkCaseStatus.RERUNNING.value,
            )
            .values(is_deleted=True, updated_by=user_id, updated_at=now)
        )
        return _result_rowcount(result)

    async def sync_run_progress_from_cases(self, run_id: int, *, user_id: int) -> None:
        cases = await self.list_cases_for_run(run_id)
        success_count = sum(
            1 for case in cases if case.status == BenchmarkCaseStatus.SUCCESS.value
        )
        failed_count = sum(
            1
            for case in cases
            if case.status
            not in {
                BenchmarkCaseStatus.SUCCESS.value,
                BenchmarkCaseStatus.RERUNNING.value,
            }
        )
        processed_count = success_count + failed_count
        now = datetime.now().astimezone()
        await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(
                ChatbiBenchmarkRun.id == run_id,
                ChatbiBenchmarkRun.is_deleted.is_(False),
            )
            .values(
                processed_count=processed_count,
                success_count=success_count,
                failed_count=failed_count,
                updated_by=user_id,
                updated_at=now,
            )
        )

    async def prepare_run_for_resume(self, run_id: int, user_id: int) -> bool:
        """将可续跑任务重置为 PENDING，保留已有样本结果。"""
        run = await self.get_run_for_user(run_id, user_id)
        if run is None:
            return False
        resumable = {
            BenchmarkRunStatus.RUNNING.value,
            BenchmarkRunStatus.FAILED.value,
            BenchmarkRunStatus.CANCELED.value,
            BenchmarkRunStatus.PENDING.value,
        }
        if run.status == BenchmarkRunStatus.SUCCESS.value:
            if int(run.processed_count) >= int(run.total_count):
                return False
        elif run.status not in resumable:
            return False
        now = datetime.now().astimezone()
        result = await self._session.execute(
            update(ChatbiBenchmarkRun)
            .where(
                ChatbiBenchmarkRun.id == run_id,
                ChatbiBenchmarkRun.created_by == user_id,
                ChatbiBenchmarkRun.is_deleted.is_(False),
            )
            .values(
                status=BenchmarkRunStatus.PENDING.value,
                last_error=None,
                finished_at=None,
                updated_by=user_id,
                updated_at=now,
            )
        )
        return _result_rowcount(result) > 0


__all__ = ["ChatbiBenchmarkRepository"]
