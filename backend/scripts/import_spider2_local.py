"""导入 Spider2-SQLite (chatbi_local) 到 ChatBI benchmark 业务表。

用法：
  python scripts/import_spider2_local.py --root /path/to/Spider2/spider2-lite --user-id 1
  python scripts/import_spider2_local.py --root /path/to/Spider2/spider2-lite --skip-preprocess
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

from app.services.system.chatbi.datasource.connectors import sqlite as _sqlite_connector  # noqa: E402

PreprocessMode = Literal["inline", "enqueue", "skip"]


def _settings() -> Any:
    return get_settings()


def _patch_benchmark_root(root: Path) -> None:
    """临时替换 SQLite connector 的 _benchmark_root，使其指向当前数据集根目录。"""
    _sqlite_connector._benchmark_root = lambda: root


def _load_samples(root: Path) -> list[dict[str, Any]]:
    path = root / "chatbi_local.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"Spider2 样本文件不存在: {path}")
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            samples.append(json.loads(line))
    return samples


def _db_file(root: Path, db_name: str) -> str | None:
    """返回相对于 CHATBI_BENCHMARK_ROOT 的 SQLite 路径；数据库不存在时返回 None。"""
    settings = _settings()
    benchmark_root = Path(settings.chatbi_benchmark_root).resolve()
    spider2_rel = root.resolve().relative_to(benchmark_root)
    direct = spider2_rel / "resource" / "databases" / "spider2-localdb" / f"{db_name}.sqlite"
    if (benchmark_root / direct).is_file():
        return direct.as_posix()
    localdb_dir = root / "resource" / "databases" / "spider2-localdb"
    if localdb_dir.is_dir():
        name_lower = db_name.lower().replace("_", "")
        for f in localdb_dir.iterdir():
            if f.suffix == ".sqlite" and f.stem.lower().replace("_", "").replace("-", "") == name_lower:
                return (spider2_rel / f.relative_to(root)).as_posix()
    return None


async def _ensure_datasource(
    *,
    ds_repo: ChatbiDatasourceRepository,
    user_id: int,
    db_name: str,
    db_file: str,
) -> int:
    name = f"SPIDER2-LOCAL:{db_name}"
    existing = await ds_repo.get_active_by_name_for_user(name, user_id)
    if existing is not None:
        return existing.id
    payload = ChatbiDatasourceCreateInput(
        user_id=user_id,
        name=name,
        connector_type="SQLITE",
        host=None,
        port=None,
        database=db_name,
        schema_name=None,
        username=None,
        password=None,
        extra_params={"db_file": db_file},
        remark="Spider2-SQLite local benchmark datasource",
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
    db_name: str,
    mode: PreprocessMode,
) -> None:
    if mode == "skip":
        return

    if await task_repo.has_active_task(datasource_id):
        raise RuntimeError(
            f"数据源 {db_name} (id={datasource_id}) 已有进行中的预处理任务，请稍后再试"
        )

    if mode == "enqueue":
        record = await ds_service.enqueue_preprocess(
            ChatbiDatasourcePreprocessInput(
                user_id=user_id,
                datasource_id=datasource_id,
            ),
        )
        print(f"  [{db_name}] 预处理已入队 task_id={record.task_id}（需 run-workers 消费）")
        return

    task_id = await task_repo.create_task(
        datasource_id=datasource_id,
        task_type=TaskType.PREPROCESS_SCHEMA.value,
        user_id=user_id,
    )
    await unit_of_work.commit()
    print(f"  [{db_name}] 预处理开始 task_id={task_id} ...")
    await ds_service.process_preprocess_task(task_id)
    task = await task_repo.get_task_for_update(task_id)
    if task is None or task.status != TaskStatus.SUCCESS.value:
        error = (task.last_error if task else None) or "未知错误"
        raise RuntimeError(f"数据源 {db_name} (id={datasource_id}) 预处理失败: {error}")
    print(f"  [{db_name}] 预处理完成 task_id={task_id}")


async def import_spider2_local(
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
                dataset_code="SPIDER2-LOCAL",
                display_name="Spider2 Local SQLite",
                description="Spider2-SQLite local benchmark dataset (135 queries, 30 databases)",
                current_version="LOCAL",
                user_id=user_id,
            )
            db_names = sorted({str(item["db"]) for item in samples})
            skipped_dbs: list[str] = []
            available_dbs: dict[str, str] = {}
            for db_name in db_names:
                db_file = _db_file(root, db_name)
                if db_file is None:
                    skipped_dbs.append(db_name)
                else:
                    available_dbs[db_name] = db_file
            if skipped_dbs:
                print(f"  跳过 {len(skipped_dbs)} 个无 SQLite 数据库的 db_name: {', '.join(skipped_dbs)}")
            datasource_by_db: dict[str, int] = {}
            for order, db_name in enumerate(sorted(available_dbs)):
                datasource_id = await _ensure_datasource(
                    ds_repo=ds_repo,
                    user_id=user_id,
                    db_name=db_name,
                    db_file=available_dbs[db_name],
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
                        db_name=db_name,
                        mode=preprocess_mode,
                    )
                await benchmark_repo.upsert_dataset_datasource(
                    dataset_id=dataset_id,
                    datasource_id=datasource_id,
                    db_id=db_name,
                    display_name=db_name,
                    status="READY",
                    sort_order=order,
                    user_id=user_id,
                )
                datasource_by_db[db_name] = datasource_id
            imported = 0
            for index, item in enumerate(samples):
                db_name = str(item["db"])
                if db_name not in datasource_by_db:
                    continue
                gold_sql = ""
                evidence = ""
                instance_id = item.get("instance_id", f"local{index}")
                await benchmark_repo.upsert_sample(
                    sample_code=f"{db_name}:{instance_id}:{index}",
                    dataset_id=dataset_id,
                    dataset_version="LOCAL",
                    datasource_id=datasource_by_db[db_name],
                    db_id=db_name,
                    source_group="local",
                    question=str(item.get("question") or ""),
                    gold_sql=gold_sql,
                    evidence=evidence,
                    ref_json=build_reference_json(gold_sql, evidence),
                    user_id=user_id,
                )
                imported += 1
            await benchmark_repo.refresh_dataset_datasource_counts(dataset_id)
            await benchmark_repo.refresh_dataset_counts(dataset_id, user_id=user_id)
            await unit_of_work.commit()
            print(f"Imported Spider2-LOCAL: dataset_id={dataset_id}, samples={imported}/{len(samples)}, db_ids={len(datasource_by_db)}/{len(db_names)}")
            if skipped_dbs:
                print(f"  跳过的 db_name（无 SQLite）: {', '.join(skipped_dbs)}")
    finally:
        await file_access.aclose()
        await database.dispose()


def _resolve_root(raw_root: str | None) -> Path:
    if raw_root:
        return Path(raw_root).resolve()
    settings = _settings()
    if settings.chatbi_benchmark_root is not None:
        return (Path(settings.chatbi_benchmark_root) / "Spider2" / "spider2-lite").resolve()
    return Path("/mnt/benchmarks/Spider2/spider2-lite").resolve()


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
    parser = argparse.ArgumentParser(description="导入 Spider2-SQLite local benchmark 数据")
    parser.add_argument(
        "--root",
        default=None,
        help="Spider2 spider2-lite 根目录（含 chatbi_local.jsonl 与 resource/databases/）",
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
        help="跳过完整预处理，仅写入原始 db_schema",
    )
    args = parser.parse_args()
    root = _resolve_root(args.root)
    user_id = _resolve_user_id(args.user_id)
    preprocess_mode = _resolve_preprocess_mode(
        enqueue_only=args.enqueue_only,
        skip_preprocess=args.skip_preprocess,
    )
    asyncio.run(
        import_spider2_local(
            root=root,
            user_id=user_id,
            preprocess_mode=preprocess_mode,
        )
    )


if __name__ == "__main__":
    main()
