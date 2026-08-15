"""导入 BIRD-DEV 到 ChatBI benchmark 业务表。

用法：
  python scripts/import_bird_dev.py --root /path/to/BIRD-DEV --user-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED = PROJECT_ROOT.parents[1] / "cogmait-backend-v2" / "shared"
for path in (SHARED, PROJECT_ROOT):
    sys.path.insert(0, str(path))


def _bootstrap_env() -> None:
    """与 run.py 一致：将 .env / .env.local 注入 os.environ。"""
    import os
    for name in (".env", ".env.local"):
        path = PROJECT_ROOT / name
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if name == ".env.local":
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)


_bootstrap_env()


class _ScriptFileAccessService:
    """BIRD 导入不走表格上传，无需连接 main_api 文件服务。"""
    async def aclose(self) -> None:
        return


from app.core.config import get_settings  # noqa: E402
from app.core.database import get_default_database  # noqa: E402
from app.core.redis import get_redis_client  # noqa: E402
from app.domain.system.chatbi import (  # noqa: E402
    ChatbiDatasourceCreateInput,
    ChatbiDatasourcePreprocessInput,
    TaskStatus,
    TaskType,
)
from app.repositories.system.chatbi import ChatbiBenchmarkRepository  # noqa: E402
from app.repositories.system.chatbi.datasource import ChatbiDatasourceRepository  # noqa: E402
from app.repositories.system.chatbi.task import ChatbiTaskRepository  # noqa: E402
from app.services.system.chatbi.benchmark import build_reference_json  # noqa: E402
from app.services.system.chatbi.datasource.connectors import get_connector  # noqa: E402
from app.services.system.chatbi.datasource.credential_encryption_service import (  # noqa: E402
    ChatbiCredentialEncryptionService,
)
from app.services.system.chatbi.datasource.db_connection_service import (  # noqa: E402
    ChatbiDbConnectionService,
)
from app.services.system.chatbi.datasource_service import ChatbiDatasourceService  # noqa: E402
from app.services.system.chatbi.vector import (  # noqa: E402
    build_chatbi_vector_settings,
    initialize_chatbi_vector_backend,
)
from app.services.system.llm_service import get_default_llm_service  # noqa: E402
from cogmait_shared.db import UnitOfWork  # noqa: E402

PreprocessMode = Literal["inline", "enqueue", "skip"]


def _settings() -> Any:
    return get_settings()


def _load_samples(root: Path) -> list[dict[str, Any]]:
    path = root / "dev.json"
    if not path.is_file():
        raise FileNotFoundError(f"BIRD-DEV 样本文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _db_file(root: Path, db_id: str) -> str:
    """返回相对于 CHATBI_BENCHMARK_ROOT 的 SQLite 路径。"""
    settings = _settings()
    benchmark_root = Path(settings.chatbi_benchmark_root).resolve()
    bird_rel = root.resolve().relative_to(benchmark_root)
    relative = bird_rel / "dev_databases" / db_id / f"{db_id}.sqlite"
    if not (benchmark_root / relative).is_file():
        raise FileNotFoundError(f"SQLite 数据库不存在: {benchmark_root / relative}")
    return relative.as_posix()


async def _ensure_datasource(
    *,
    ds_repo: ChatbiDatasourceRepository,
    user_id: int,
    db_id: str,
    db_file: str,
) -> int:
    name = f"BIRD-DEV:{db_id}"
    existing = await ds_repo.get_active_by_name_for_user(name, user_id)
    if existing is not None:
        return existing.id
    payload = ChatbiDatasourceCreateInput(
        user_id=user_id,
        name=name,
        connector_type="SQLITE",
        host=None,
        port=None,
        database=db_id,
        schema_name=None,
        username=None,
        password=None,
        extra_params={"db_file": db_file},
        remark="BIRD-DEV SQLite benchmark datasource",
    )
    encrypted_password = ChatbiCredentialEncryptionService(
        key_material=_settings().chatbi_datasource_credential_encryption_key,
    ).encrypt(str(payload.password))
    return await ds_repo.create(
        payload,
        encrypted_password=encrypted_password,
    )


async def _refresh_schema_only(
    *,
    ds_repo: ChatbiDatasourceRepository,
    datasource_id: int,
    user_id: int,
) -> None:
    """仅写入 db_schema，不建 schema 向量（开发调试用）。"""
    conn = await ds_repo.get_connection_for_user(datasource_id, user_id)
    if conn is None:
        raise RuntimeError(f"数据源不存在: {datasource_id}")
    db_conn = ChatbiDbConnectionService(
        datasource_repo=ds_repo,
        encryption=ChatbiCredentialEncryptionService(
            key_material=_settings().chatbi_datasource_credential_encryption_key,
        ),
    )
    cfg = db_conn.build_connector_config(conn)
    structure = await get_connector(conn.connector_type).get_structure(cfg)
    await ds_repo.update_db_schema(
        datasource_id,
        db_schema=structure.to_json_dict(),
        updated_by=user_id,
    )


async def _run_preprocess(
    *,
    ds_service: ChatbiDatasourceService,
    task_repo: ChatbiTaskRepository,
    unit_of_work: UnitOfWork,
    datasource_id: int,
    user_id: int,
    db_id: str,
    mode: PreprocessMode,
) -> None:
    if mode == "skip":
        return

    if await task_repo.has_active_task(datasource_id):
        raise RuntimeError(
            f"数据源 {db_id} (id={datasource_id}) 已有进行中的预处理任务，请稍后再试"
        )

    if mode == "enqueue":
        record = await ds_service.enqueue_preprocess(
            ChatbiDatasourcePreprocessInput(
                user_id=user_id,
                datasource_id=datasource_id,
            ),
        )
        print(f"  [{db_id}] 预处理已入队 task_id={record.task_id}（需 run-workers 消费）")
        return

    task_id = await task_repo.create_task(
        datasource_id=datasource_id,
        task_type=TaskType.PREPROCESS_SCHEMA.value,
        user_id=user_id,
    )
    await unit_of_work.commit()
    print(f"  [{db_id}] 预处理开始 task_id={task_id} ...")
    await ds_service.process_preprocess_task(task_id)
    task = await task_repo.get_task_for_update(task_id)
    if task is None or task.status != TaskStatus.SUCCESS.value:
        error = (task.last_error if task else None) or "未知错误"
        raise RuntimeError(f"数据源 {db_id} (id={datasource_id}) 预处理失败: {error}")
    print(f"  [{db_id}] 预处理完成 task_id={task_id}")


async def import_bird_dev(
    *,
    root: Path,
    user_id: int,
    preprocess_mode: PreprocessMode,
) -> None:
    settings = _settings()
    initialize_chatbi_vector_backend(build_chatbi_vector_settings(settings))

    samples = _load_samples(root)
    database = get_default_database()
    database.initialize()
    file_access: Any = _ScriptFileAccessService()
    redis = get_redis_client()
    try:
        async with database.get_session() as session:
            unit_of_work = UnitOfWork(session)
            ds_repo = ChatbiDatasourceRepository(session)
            task_repo = ChatbiTaskRepository(session)
            benchmark_repo = ChatbiBenchmarkRepository(session)
            ds_service = ChatbiDatasourceService(
                unit_of_work=unit_of_work,
                redis=redis,
                file_access_service=file_access,
                llm_service=get_default_llm_service(),
            )
            dataset_id = await benchmark_repo.upsert_dataset(
                dataset_code="BIRD-DEV",
                display_name="BIRD DEV",
                description="BIRD DEV SQLite benchmark dataset",
                current_version="DEV",
                user_id=user_id,
            )
            db_ids = sorted({str(item["db_id"]) for item in samples})
            datasource_by_db: dict[str, int] = {}
            for order, db_id in enumerate(db_ids):
                datasource_id = await _ensure_datasource(
                    ds_repo=ds_repo,
                    user_id=user_id,
                    db_id=db_id,
                    db_file=_db_file(root, db_id),
                )
                if preprocess_mode == "skip":
                    await _refresh_schema_only(
                        ds_repo=ds_repo,
                        datasource_id=datasource_id,
                        user_id=user_id,
                    )
                else:
                    await _run_preprocess(
                        ds_service=ds_service,
                        task_repo=task_repo,
                        unit_of_work=unit_of_work,
                        datasource_id=datasource_id,
                        user_id=user_id,
                        db_id=db_id,
                        mode=preprocess_mode,
                    )
                await benchmark_repo.upsert_dataset_datasource(
                    dataset_id=dataset_id,
                    datasource_id=datasource_id,
                    db_id=db_id,
                    display_name=db_id,
                    status="READY",
                    sort_order=order,
                    user_id=user_id,
                )
                datasource_by_db[db_id] = datasource_id
            for index, item in enumerate(samples):
                db_id = str(item["db_id"])
                gold_sql = str(item.get("SQL") or "")
                evidence = str(item.get("evidence") or "")
                await benchmark_repo.upsert_sample(
                    sample_code=f"{db_id}:{item.get('question_id')}:{index}",
                    dataset_id=dataset_id,
                    dataset_version="DEV",
                    datasource_id=datasource_by_db[db_id],
                    db_id=db_id,
                    source_group="dev",
                    question=str(item.get("question") or ""),
                    gold_sql=gold_sql,
                    evidence=evidence,
                    ref_json=build_reference_json(gold_sql, evidence),
                    user_id=user_id,
                )
            await benchmark_repo.refresh_dataset_datasource_counts(dataset_id)
            await benchmark_repo.refresh_dataset_counts(dataset_id, user_id=user_id)
            await unit_of_work.commit()
            print(f"Imported BIRD-DEV: dataset_id={dataset_id}, samples={len(samples)}")
    finally:
        await file_access.aclose()
        await database.dispose()


def _resolve_root(raw_root: str | None) -> Path:
    if raw_root:
        return Path(raw_root).resolve()
    settings = _settings()
    if settings.chatbi_benchmark_root is not None:
        return (Path(settings.chatbi_benchmark_root) / "BIRD-DEV").resolve()
    return Path("/mnt/benchmarks/BIRD-DEV").resolve()


def _resolve_user_id(raw_user_id: int | None) -> int:
    if raw_user_id is not None:
        return raw_user_id
    configured = _settings().chatbi_benchmark_import_user_id
    if configured is not None:
        return configured
    raise SystemExit(
        "请通过 --user-id 或 CHATBI_BENCHMARK_IMPORT_USER_ID 指定导入数据 owner 用户 ID"
    )


def _resolve_preprocess_mode(*, enqueue_only: bool, skip_preprocess: bool) -> PreprocessMode:
    if skip_preprocess and enqueue_only:
        raise SystemExit("--skip-preprocess 与 --enqueue-only 不能同时使用")
    if skip_preprocess:
        return "skip"
    if enqueue_only:
        return "enqueue"
    return "inline"


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 BIRD-DEV benchmark 数据")
    parser.add_argument(
        "--root",
        default=None,
        help="BIRD-DEV 根目录（含 dev.json 与 dev_databases/）",
    )
    parser.add_argument("--user-id", type=int, default=None, help="数据源和样本 owner 用户 ID")
    parser.add_argument(
        "--enqueue-only",
        action="store_true",
        help="仅创建预处理任务并投递 Redis，由 run-workers 异步执行",
    )
    parser.add_argument(
        "--skip-preprocess",
        action="store_true",
        help="跳过完整预处理，仅写入原始 db_schema（不含 schema 向量，问数可能失败）",
    )
    args = parser.parse_args()
    root = _resolve_root(args.root)
    user_id = _resolve_user_id(args.user_id)
    preprocess_mode = _resolve_preprocess_mode(
        enqueue_only=args.enqueue_only,
        skip_preprocess=args.skip_preprocess,
    )
    asyncio.run(
        import_bird_dev(
            root=root,
            user_id=user_id,
            preprocess_mode=preprocess_mode,
        )
    )


if __name__ == "__main__":
    main()
