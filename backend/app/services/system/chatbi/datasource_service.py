"""ChatBI 数据源业务编排。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from cogmait_shared.core.api_codes import ErrorCode
from cogmait_shared.db import IntegrityError
from cogmait_shared.observability.logging import logger
from cogmait_shared.streaming import RedisStreamPublisher, StreamPayload

from ....constants.chatbi.datasource import (
    CHATBI_DEFAULT_SCHEMA_NAME,
    CHATBI_PREPROCESS_STREAM_TASK_TYPE,
    CHATBI_PREPROCESS_TASK_STREAM,
)
from ....core.config import get_settings
from ....domain.system.chatbi import (
    ACTIVE_TASK_STATUSES,
    ChatbiDatasourceCreateInput,
    ChatbiDatasourceDeleteInput,
    ChatbiDatasourceExecuteSqlInput,
    ChatbiDatasourceFileUploadCreateInput,
    ChatbiDatasourceFromFilesInput,
    ChatbiDatasourceListParams,
    ChatbiDatasourcePreprocessInput,
    ChatbiDatasourcePreprocessRecord,
    ChatbiDatasourceRecord,
    ChatbiDatasourceUpdateInput,
    ChatbiTaskRecord,
    DataSourceOrigin,
    DataSourceType,
    TaskType,
    normalize_sqlite_extra_params,
)
from ....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from ....repositories.system.chatbi import (
    ChatbiBusinessKnowledgeRepository,
    ChatbiDatasourceRepository,
    ChatbiQsqlRepository,
    ChatbiTaskRepository,
)
from ..content_extract.file_access_service import FileAccessService, FileAccessServiceError
from ..llm_service import LLMService
from .datasource.connectors import get_connector
from .datasource.credential_encryption_service import ChatbiCredentialEncryptionService
from .datasource.db_connection_service import ChatbiDbConnectionService
from .datasource.file_import_service import (
    ChatbiFileImportService,
    build_file_upload_schema_name,
)
from .datasource.preprocess_service import ChatbiSchemaEnrichmentService
from .datasource.schema_vector_service import build_schema_vector_service
from .datasource.url_utils import parse_postgres_url
from .datasource_errors import ChatbiDatasourceServiceError, DbConnectionServiceError
from .value_index import (
    ChatbiColumnProfiler,
    ChatbiValueIndexStore,
    apply_column_profiles_to_schema,
)
from .vector import ChatbiVectorStore, build_chatbi_vector_settings


def _sanitize_extra_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """去掉 extra_params 中可能含密钥的键，避免经列表接口泄漏。"""
    if not params:
        return params
    out = dict(params)
    for key in list(out.keys()):
        lk = key.lower()
        if "password" in lk or "secret" in lk or "token" in lk:
            out.pop(key, None)
    return out


@dataclass(slots=True)
class _FileUploadConnectionConfig:
    host: str
    port: int
    database: str
    username: str
    encrypted_password: str
    extra_params: dict[str, object] | None


class ChatbiDatasourceService:
    """ChatBI 数据源业务编排。"""

    _CONNECTION_UPDATE_FIELDS = frozenset(
        {
            "host",
            "port",
            "database",
            "schema_name",
            "username",
            "password",
            "extra_params",
        }
    )
    _NAME_UNIQUE_CONSTRAINT_TOKENS = frozenset(
        {
            "uq_ais_chatbi_datasource_owner_name_active",
            "uq_ais_chatbi_datasource_name_active",
            "ais_chatbi_datasource_name",
        }
    )
    _ACTIVE_TASK_UNIQUE_CONSTRAINT_TOKENS = frozenset(
        {
            "uq_ais_chatbi_task_datasource_active",
        }
    )

    def __init__(
        self,
        *,
        unit_of_work: Any,
        redis: Redis,
        file_access_service: FileAccessService | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        self._uow = unit_of_work
        self._session = unit_of_work.session
        self._redis = redis
        self._file_access = file_access_service or FileAccessService()
        self._llm = llm_service or LLMService()
        runtime_settings = get_settings()
        self._ds_repo = ChatbiDatasourceRepository(self._session)
        self._task_repo = ChatbiTaskRepository(self._session)
        self._qsql_repo = ChatbiQsqlRepository(self._session)
        self._bizkn_repo = ChatbiBusinessKnowledgeRepository(self._session)
        self._vector_store = ChatbiVectorStore(
            session=self._session,
            store_settings=build_chatbi_vector_settings(runtime_settings),
        )
        self._encryption = ChatbiCredentialEncryptionService(
            key_material=runtime_settings.chatbi_datasource_credential_encryption_key,
        )
        self._db_conn = ChatbiDbConnectionService(
            datasource_repo=self._ds_repo,
            encryption=self._encryption,
        )
        self._publisher = RedisStreamPublisher(
            self._redis,
            stream=CHATBI_PREPROCESS_TASK_STREAM,
            key_prefix=runtime_settings.redis_key_prefix,
        )
        self._enrichment = ChatbiSchemaEnrichmentService(llm_service=self._llm)
        self._value_index = ChatbiValueIndexStore()
        self._schema_vec = build_schema_vector_service(
            session=self._session,
            llm_service=self._llm,
        )
        self._file_import = ChatbiFileImportService()

    async def aclose(self) -> None:
        """释放文件访问客户端等资源。"""

        await self._file_access.aclose()

    @staticmethod
    def _sanitize_record(record: ChatbiDatasourceRecord) -> ChatbiDatasourceRecord:
        """脱敏 extra_params 后返回 API 用记录。"""
        return replace(record, extra_params=_sanitize_extra_params(record.extra_params))

    def _encrypt_secret(self, plain_text: str) -> str:
        try:
            return self._encryption.encrypt(plain_text)
        except ValueError as exc:
            raise ChatbiDatasourceServiceError.system_error(str(exc)) from exc

    def _build_file_upload_connection_config(self, raw_url: str) -> _FileUploadConnectionConfig:
        """解析表格上传建源配置，并完成类型规整和密码加密。"""

        try:
            conn = parse_postgres_url(raw_url)
        except ValueError as exc:
            raise ChatbiDatasourceServiceError.bad_request(str(exc)) from exc
        raw_port = conn["port"]
        port = raw_port if isinstance(raw_port, int) else int(str(raw_port))
        raw_extra_params = conn.get("extra_params")
        extra_params: dict[str, object] | None = None
        if isinstance(raw_extra_params, dict):
            extra_params = {str(key): str(value) for key, value in raw_extra_params.items()}

        return _FileUploadConnectionConfig(
            host=str(conn["host"]),
            port=port,
            database=str(conn["database"]),
            username=str(conn["username"]),
            encrypted_password=self._encrypt_secret(str(conn["password"])),
            extra_params=extra_params,
        )

    async def _validate_import_files_owned(
        self,
        payload: ChatbiDatasourceFromFilesInput,
    ) -> None:
        try:
            records = await self._file_access.list_files(payload.file_ids)
        except FileAccessServiceError as exc:
            raise ChatbiDatasourceServiceError.bad_request(str(exc)) from exc

        records_by_id = {int(record.id): record for record in records}
        missing_ids = [file_id for file_id in payload.file_ids if int(file_id) not in records_by_id]
        if missing_ids:
            raise ChatbiDatasourceServiceError.bad_request("文件不存在或无权访问")
        for file_id in payload.file_ids:
            owner_id = getattr(records_by_id[int(file_id)], "created_by", None)
            if owner_id is None or int(owner_id) != payload.user_id:
                raise ChatbiDatasourceServiceError.bad_request("文件不存在或无权访问")

    @classmethod
    def _has_connection_update(cls, payload: ChatbiDatasourceUpdateInput) -> bool:
        return any(field in payload.provided_fields for field in cls._CONNECTION_UPDATE_FIELDS)

    async def list_datasources(
        self, params: ChatbiDatasourceListParams
    ) -> tuple[list[ChatbiDatasourceRecord], int]:
        """分页列出当前用户的数据源。"""

        self._validate_connector_type_filter(params.connector_type_filter)
        rows, total = await self._ds_repo.list_for_user(params)
        return [self._sanitize_record(r) for r in rows], total

    async def create_external(self, payload: ChatbiDatasourceCreateInput) -> ChatbiDatasourceRecord:
        """创建外部库数据源并入队结构预处理任务。"""

        self._validate_connector_type(payload.connector_type)
        await self._ensure_unique_name(payload.name, user_id=payload.user_id)
        password = payload.password
        if password is None:
            raise ChatbiDatasourceServiceError.bad_request("password 不能为空")
        enc = self._encrypt_secret(password)
        ds_id = await self._ds_repo.create(payload, encrypted_password=enc)
        await self._create_preprocess_task_and_publish(
            datasource_id=ds_id,
            task_type=TaskType.PREPROCESS_SCHEMA.value,
            user_id=payload.user_id,
            cleanup_datasource_id=ds_id,
        )
        record = await self._ds_repo.get_for_user(ds_id, payload.user_id)
        if record is None:
            raise ChatbiDatasourceServiceError.system_error("数据源创建后不存在")
        return self._sanitize_record(record)

    async def create_from_files(
        self, payload: ChatbiDatasourceFromFilesInput
    ) -> ChatbiDatasourceRecord:
        """按上传表格文件建源、分配隔离 schema，并入队导入与结构采集。"""

        raw_url = (get_settings().chatbi_file_upload_database_url or "").strip()
        if not raw_url:
            raise ChatbiDatasourceServiceError.bad_request(
                "未配置 CHATBI_FILE_UPLOAD_DATABASE_URL，无法创建表格上传数据源",
            )
        await self._ensure_unique_name(payload.name, user_id=payload.user_id)
        connection_config = self._build_file_upload_connection_config(raw_url)
        await self._validate_import_files_owned(payload)
        ds_id = await self._ds_repo.create_file_upload(
            ChatbiDatasourceFileUploadCreateInput(
                user_id=payload.user_id,
                name=payload.name,
                remark=payload.remark,
                file_ids=payload.file_ids,
                host=connection_config.host,
                port=connection_config.port,
                database=connection_config.database,
                schema_name=CHATBI_DEFAULT_SCHEMA_NAME,
                username=connection_config.username,
                encrypted_password=connection_config.encrypted_password,
                extra_params=connection_config.extra_params,
            )
        )
        await self._ds_repo.update_schema_name(
            ds_id,
            build_file_upload_schema_name(payload.name, ds_id),
            user_id=payload.user_id,
        )
        await self._create_preprocess_task_and_publish(
            datasource_id=ds_id,
            task_type=TaskType.FILE_UPLOAD_IMPORT_AND_SCHEMA.value,
            user_id=payload.user_id,
            total_count=2,
            cleanup_datasource_id=ds_id,
        )
        record = await self._ds_repo.get_for_user(ds_id, payload.user_id)
        if record is None:
            raise ChatbiDatasourceServiceError.system_error("数据源创建后不存在")
        return self._sanitize_record(record)

    async def get_detail(self, datasource_id: int, user_id: int) -> ChatbiDatasourceRecord:
        """按 ID 返回数据源详情（含 db_schema 快照）。"""

        record = await self._ds_repo.get_for_user(datasource_id, user_id)
        if record is None:
            raise ChatbiDatasourceServiceError.not_found()
        return self._sanitize_record(record)

    async def update_datasource(
        self,
        datasource_id: int,
        payload: ChatbiDatasourceUpdateInput,
    ) -> ChatbiDatasourceRecord:
        """更新数据源连接参数或展示字段。"""

        record = await self._ds_repo.get_for_user(datasource_id, payload.user_id)
        if record is None:
            raise ChatbiDatasourceServiceError.not_found()
        has_connection_update = self._has_connection_update(payload)
        if record.origin == DataSourceOrigin.FILE_UPLOAD.value and has_connection_update:
            raise ChatbiDatasourceServiceError.bad_request("表格上传数据源不允许修改连接信息")
        if (
            record.origin == DataSourceOrigin.EXTERNAL.value
            and has_connection_update
            and await self._task_repo.has_active_task(datasource_id)
        ):
            raise ChatbiDatasourceServiceError.status_invalid("该数据源已有未结束的预处理任务")
        self._validate_update_for_connector(record, payload)
        if (
            "name" in payload.provided_fields
            and payload.name is not None
            and payload.name != record.name
        ):
            await self._ensure_unique_name(
                payload.name,
                user_id=payload.user_id,
                exclude_id=datasource_id,
            )
        enc: str | None = None
        if "password" in payload.provided_fields and payload.password is not None:
            enc = self._encrypt_secret(payload.password)
        ok = await self._ds_repo.update_for_user(
            datasource_id,
            payload.user_id,
            payload,
            encrypted_password=enc,
        )
        if not ok:
            raise ChatbiDatasourceServiceError.not_found()
        if record.origin == DataSourceOrigin.EXTERNAL.value and has_connection_update:
            await self._ds_repo.clear_db_schema(datasource_id, updated_by=payload.user_id)
            await self._schema_vec.clear_vectors_for_datasource(
                datasource_id=datasource_id,
                user_id=payload.user_id,
            )
            await self._create_preprocess_task_and_publish(
                datasource_id=datasource_id,
                task_type=TaskType.PREPROCESS_SCHEMA.value,
                user_id=payload.user_id,
            )
        else:
            await self._commit()
        record = await self._ds_repo.get_for_user(datasource_id, payload.user_id)
        if record is None:
            raise ChatbiDatasourceServiceError.not_found()
        return self._sanitize_record(record)

    async def _purge_datasource_related_data(self, *, datasource_id: int, user_id: int) -> None:
        """删除数据源前清理其 Q-SQL、业务知识及对应向量。"""
        bizkn_ids = await self._bizkn_repo.soft_delete_by_datasource(datasource_id, user_id)
        await self._qsql_repo.soft_delete_by_datasource(datasource_id, user_id)
        await self._vector_store.soft_delete_qsql_vectors_by_datasource(
            datasource_id=datasource_id,
            user_id=user_id,
        )
        await self._vector_store.soft_delete_business_knowledge_vectors_by_ids(
            record_ids=bizkn_ids,
            user_id=user_id,
        )

    async def delete_datasource(self, payload: ChatbiDatasourceDeleteInput) -> None:
        """软删除数据源；先清理 Q-SQL/业务知识，表格上传类同时删除 PG 隔离 schema。"""

        record = await self._ds_repo.get_for_user(payload.datasource_id, payload.user_id)
        if record is None:
            raise ChatbiDatasourceServiceError.not_found()
        if await self._task_repo.has_active_task(payload.datasource_id):
            raise ChatbiDatasourceServiceError.status_invalid("该数据源已有未结束的预处理任务")
        file_upload_cleanup: tuple[dict[str, Any], str] | None = None
        if record.origin == DataSourceOrigin.FILE_UPLOAD.value:
            schema = (record.schema_name or "").strip()
            if schema:
                conn = await self._ds_repo.get_connection_for_user(
                    payload.datasource_id,
                    payload.user_id,
                )
                if conn is None:
                    raise ChatbiDatasourceServiceError.not_found()
                file_upload_cleanup = (
                    self._db_conn.build_connector_config(conn),
                    schema,
                )
        await self._purge_datasource_related_data(
            datasource_id=payload.datasource_id,
            user_id=payload.user_id,
        )
        ok = await self._ds_repo.soft_delete(payload.datasource_id, payload.user_id)
        if not ok:
            raise ChatbiDatasourceServiceError.not_found()
        await self._schema_vec.clear_vectors_for_datasource(
            datasource_id=payload.datasource_id,
            user_id=payload.user_id,
        )
        await self._uow.commit()
        if file_upload_cleanup is not None:
            cfg, schema = file_upload_cleanup
            try:
                await self._file_import.drop_schema(cfg, schema_name=schema)
            except Exception:
                logger.exception(
                    "ChatBI file upload schema cleanup failed datasource_id={} schema={}",
                    payload.datasource_id,
                    schema,
                )

    async def test_connection(self, datasource_id: int, user_id: int) -> None:
        """使用已存凭证对目标库执行连接探测。"""

        await self._db_conn.test_connection_for_user(datasource_id, user_id)

    async def execute_readonly_sql(
        self,
        payload: ChatbiDatasourceExecuteSqlInput,
    ) -> tuple[list[str], list[dict[str, Any]], bool]:
        """只读执行单条 SQL，并按上限截断返回行。"""

        try:
            return await self._db_conn.execute_readonly_sql(
                datasource_id=payload.datasource_id,
                user_id=payload.user_id,
                sql=payload.sql,
            )
        except ChatbiDatasourceServiceError as exc:
            if exc.code != ErrorCode.CONNECTION_FAILED:
                raise
            logger.warning(
                "ChatBI datasource SQL execution failed datasource_id={} user_id={} error={}",
                payload.datasource_id,
                payload.user_id,
                exc.message,
            )
            raise ChatbiDatasourceServiceError.connection_failed(
                "SQL 执行失败，请检查 SQL 或数据源配置",
            ) from exc

    async def enqueue_preprocess(
        self, payload: ChatbiDatasourcePreprocessInput
    ) -> ChatbiDatasourcePreprocessRecord:
        """为已有数据源创建预处理任务并投递 Redis Stream。"""

        if await self._ds_repo.get_for_user(payload.datasource_id, payload.user_id) is None:
            raise ChatbiDatasourceServiceError.not_found()
        if await self._task_repo.has_active_task(payload.datasource_id):
            raise ChatbiDatasourceServiceError.status_invalid("该数据源已有未结束的预处理任务")
        task_id = await self._create_preprocess_task_and_publish(
            datasource_id=payload.datasource_id,
            task_type=TaskType.PREPROCESS_SCHEMA.value,
            user_id=payload.user_id,
        )
        return ChatbiDatasourcePreprocessRecord(task_id=task_id)

    async def process_preprocess_task(self, task_id: int) -> None:
        """Worker 消费入口：可选表格导入、采集结构、LLM 补全描述与列向量重建。"""

        task = await self._task_repo.get_task_for_update(task_id)
        if task is None:
            return
        if not self._can_run_preprocess_task(task):
            return
        user_id = task.created_by
        try:
            if not await self._task_repo.mark_running(task.id, user_id=user_id):
                return
            await self._uow.commit()
            uid = int(user_id or 0)
            record = await self._load_preprocess_datasource(task.datasource_id, uid)
            record = await self._run_file_import_stage(task, record, user_id=uid)
            await self._refresh_preprocess_schema(task, record)
            if not await self._task_repo.mark_success(task.id, user_id=user_id):
                return
            await self._uow.commit()
        except ChatbiDatasourceServiceError as exc:
            await self._mark_task_failed(task_id, str(exc.message), user_id=user_id)
        except Exception as exc:
            await self._mark_task_failed(task_id, str(exc), user_id=user_id)

    @staticmethod
    def _can_run_preprocess_task(task: ChatbiTaskRecord) -> bool:
        return task.status in ACTIVE_TASK_STATUSES

    async def _load_preprocess_datasource(
        self,
        datasource_id: int,
        user_id: int,
    ) -> ChatbiDatasourceRecord:
        """按任务归属加载数据源；任务执行期间统一转换已删除或无权访问错误。"""

        record = await self._ds_repo.get_for_user(datasource_id, user_id)
        if record is None:
            raise ChatbiDatasourceServiceError.not_found("数据源不存在或已删除")
        return record

    async def _run_file_import_stage(
        self,
        task: ChatbiTaskRecord,
        record: ChatbiDatasourceRecord,
        *,
        user_id: int,
    ) -> ChatbiDatasourceRecord:
        """表格上传任务先完成文件导入，并在导入后重新读取最新数据源。"""

        if (
            task.task_type != TaskType.FILE_UPLOAD_IMPORT_AND_SCHEMA.value
            or int(task.processed_count or 0) >= 1
        ):
            return record
        await self._run_file_import(record, user_id=user_id)
        await self._task_repo.set_processed(task.id, 1, user_id=task.created_by)
        await self._uow.commit()
        return await self._load_preprocess_datasource(task.datasource_id, user_id)

    async def _refresh_preprocess_schema(
        self,
        task: ChatbiTaskRecord,
        record: ChatbiDatasourceRecord,
    ) -> None:
        """采集并保存 schema，LLM 补全失败时沿用原始结构继续完成任务。"""

        owner_id = int(task.created_by or 0)
        structure = await self._load_datasource_structure(record, user_id=owner_id)
        profiles = await self._profile_preprocess_columns(record, structure, user_id=owner_id)
        apply_column_profiles_to_schema(structure, profiles)
        try:
            enriched = await self._enrichment.enrich_structure(structure)
        except Exception:
            logger.exception(
                "ChatBI schema enrichment failed; using raw structure "
                "task_id={} datasource_id={}",
                task.id,
                task.datasource_id,
            )
            enriched = structure
        apply_column_profiles_to_schema(enriched, profiles)
        db_schema = enriched.to_json_dict()
        await self._ds_repo.update_db_schema(
            task.datasource_id,
            db_schema=db_schema,
            updated_by=task.created_by,
        )
        await self._schema_vec.rebuild_vectors_for_schema(
            datasource_id=task.datasource_id,
            db_schema=db_schema,
            user_id=task.created_by,
        )
        await self._value_index.rebuild_datasource(
            datasource_id=task.datasource_id,
            db_name=enriched.database,
            profiles=profiles,
        )

    async def _profile_preprocess_columns(
        self,
        record: ChatbiDatasourceRecord,
        structure: Any,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        if not isinstance(structure, ChatbiDbSchemaRecord):
            return {}

        async def execute_sql(
            sql: str,
            max_rows: int,
            timeout_seconds: float,
        ) -> tuple[list[str], list[dict[str, Any]], bool]:
            return await self._db_conn.execute_readonly_sql(
                datasource_id=record.id,
                user_id=user_id,
                sql=sql,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )

        try:
            return await ChatbiColumnProfiler(execute_sql).profile_schema(structure)
        except Exception:
            logger.exception(
                "ChatBI column profiling failed; continuing without value index datasource_id={}",
                record.id,
            )
            return {}

    async def _load_datasource_structure(
        self,
        record: ChatbiDatasourceRecord,
        *,
        user_id: int,
    ) -> Any:
        """使用当前保存的连接信息读取数据库结构。"""

        conn = await self._ds_repo.get_connection_for_user(record.id, user_id)
        if conn is None:
            raise ChatbiDatasourceServiceError.not_found("数据源不存在或已删除")
        connector = get_connector(record.connector_type)
        return await connector.get_structure(self._db_conn.build_connector_config(conn))

    async def _ensure_unique_name(
        self,
        name: str,
        *,
        user_id: int,
        exclude_id: int | None = None,
    ) -> None:
        existing = await self._ds_repo.get_active_by_name_for_user(name, user_id)
        if existing is None:
            return
        if exclude_id is not None and existing.id == exclude_id:
            return
        raise ChatbiDatasourceServiceError.bad_request("数据源名称已存在")

    async def _commit(self) -> None:
        try:
            await self._uow.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._map_integrity_error(exc) from exc

    async def _create_preprocess_task_and_publish(
        self,
        *,
        datasource_id: int,
        task_type: str,
        user_id: int,
        total_count: int = 1,
        cleanup_datasource_id: int | None = None,
    ) -> int:
        """创建预处理任务并投递 Stream；创建数据源场景失败时清理刚建的数据源。"""
        task_id = await self._task_repo.create_task(
            datasource_id=datasource_id,
            task_type=task_type,
            user_id=user_id,
            total_count=total_count,
        )
        await self._commit()
        try:
            await self._publish_preprocess_task(task_id)
        except Exception as exc:
            await self._mark_preprocess_publish_failed(
                task_id=task_id,
                cleanup_datasource_id=cleanup_datasource_id,
                user_id=user_id,
                exc=exc,
            )
        return task_id

    async def _publish_preprocess_task(self, task_id: int) -> None:
        await self._publisher.publish(
            StreamPayload(
                task_type=CHATBI_PREPROCESS_STREAM_TASK_TYPE,
                payload={"task_id": task_id},
            )
        )

    @staticmethod
    def _validate_connector_type(connector_type: str) -> None:
        if connector_type not in {DataSourceType.POSTGRESQL.value, DataSourceType.SQLITE.value}:
            raise ChatbiDatasourceServiceError.bad_request("connector_type 取值不支持")

    @staticmethod
    def _validate_update_for_connector(
        record: ChatbiDatasourceRecord,
        payload: ChatbiDatasourceUpdateInput,
    ) -> None:
        if record.connector_type != DataSourceType.SQLITE.value:
            return
        unsupported = {
            "host",
            "port",
            "schema_name",
            "username",
            "password",
        } & set(payload.provided_fields)
        if unsupported:
            raise ChatbiDatasourceServiceError.bad_request("SQLite 数据源不支持修改网络连接字段")
        if "extra_params" in payload.provided_fields:
            try:
                payload.extra_params = normalize_sqlite_extra_params(payload.extra_params)
            except ValueError as exc:
                raise ChatbiDatasourceServiceError.bad_request(str(exc)) from exc

    @classmethod
    def _validate_connector_type_filter(cls, connector_type: str | None) -> None:
        if connector_type is None:
            return
        cls._validate_connector_type(connector_type)

    async def _mark_preprocess_publish_failed(
        self,
        *,
        task_id: int,
        cleanup_datasource_id: int | None,
        user_id: int,
        exc: Exception,
    ) -> None:
        message = f"任务投递失败：{exc}"
        await self._task_repo.fail_publish(task_id, message)
        if cleanup_datasource_id is not None:
            await self._ds_repo.soft_delete(cleanup_datasource_id, user_id)
        await self._commit()
        raise ChatbiDatasourceServiceError.system_error(message) from exc

    @classmethod
    def _map_integrity_error(cls, exc: IntegrityError) -> ChatbiDatasourceServiceError:
        if cls._is_name_unique_violation(exc):
            return ChatbiDatasourceServiceError.bad_request("数据源名称已存在")
        if cls._is_active_task_unique_violation(exc):
            return ChatbiDatasourceServiceError.status_invalid("该数据源已有未结束的预处理任务")
        return ChatbiDatasourceServiceError.bad_request("数据完整性约束冲突")

    @classmethod
    def _is_name_unique_violation(cls, exc: IntegrityError) -> bool:
        return cls._integrity_error_has_token(exc, cls._NAME_UNIQUE_CONSTRAINT_TOKENS)

    @classmethod
    def _is_active_task_unique_violation(cls, exc: IntegrityError) -> bool:
        return cls._integrity_error_has_token(exc, cls._ACTIVE_TASK_UNIQUE_CONSTRAINT_TOKENS)

    @staticmethod
    def _integrity_error_has_token(exc: IntegrityError, tokens: frozenset[str]) -> bool:
        original = getattr(exc, "orig", None)
        diag = getattr(original, "diag", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name and str(constraint_name).lower() in tokens:
            return True
        message = str(original or exc).lower()
        return any(token in message for token in tokens)

    async def _mark_task_failed(self, task_id: int, message: str, *, user_id: int | None) -> None:
        """回滚当前事务并将任务标记为失败。"""

        await self._session.rollback()
        if await self._task_repo.mark_failed(task_id, message, user_id=user_id):
            await self._uow.commit()

    async def _run_file_import(self, record: ChatbiDatasourceRecord, user_id: int) -> None:
        """下载绑定表格文件并导入到数据源目标 schema。"""

        ids = list(record.import_file_ids or [])
        if not ids:
            raise ChatbiDatasourceServiceError.bad_request("缺少 import_file_ids")
        schema = (record.schema_name or "").strip()
        if not schema:
            raise ChatbiDatasourceServiceError.bad_request("缺少目标 schema")
        conn = await self._ds_repo.get_connection_for_user(record.id, user_id)
        if conn is None:
            raise ChatbiDatasourceServiceError.not_found("数据源不存在或已删除")
        tmp = Path(tempfile.mkdtemp(prefix="chatbi_import_"))
        paths: list[tuple[int, Path, str]] = []
        try:
            for fid in ids:
                downloaded = await self._file_access.download_file(fid, target_dir=tmp)
                paths.append((fid, downloaded.local_path, downloaded.file_record.original_name))
            cfg = self._db_conn.build_connector_config(conn)
            await self._file_import.import_files(
                cfg,
                schema_name=schema,
                files=paths,
                replace_schema=True,
            )
        finally:
            for _fid, p, _name in paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                tmp.rmdir()
            except OSError:
                pass


__all__ = [
    "ChatbiDatasourceService",
    "ChatbiDatasourceServiceError",
    "DbConnectionServiceError",
]
