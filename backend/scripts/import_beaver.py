"""导入 BEAVER benchmark 到 ChatBI benchmark 业务表。

数据存储在远程 MySQL (47.94.248.19:18003)。
样本来 example.json（每域1条 few-shot 样例）。
完整数据需从 HuggingFace 下载 dev.json 后扩展。

用法：
  python scripts/import_beaver.py --user-id 1 --skip-preprocess
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

PreprocessMode = Literal["inline", "enqueue", "skip"]

MYSQL_HOST = "47.94.248.19"
MYSQL_PORT = 18003
MYSQL_USER = "root"
MYSQL_PASSWORD = "123456"

# domain → MySQL database name
DOMAIN_DB_MAP = {
    "dw": "dw",
    "dw_real": "dw",  # dw_real 复用 dw 数据库
    "neutron": "neutron",
    "nova": "nova",
}


def _settings() -> Any:
    return get_settings()


def _load_samples(root: Path) -> list[dict[str, Any]]:
    """加载所有域的 example.json 样本。"""
    samples = []
    for domain in ["dw", "dw_real", "neutron", "nova"]:
        path = root / "beaver" / "data" / domain / "example.json"
        if not path.is_file():
            print(f"  WARN: {path} 不存在，跳过")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_domain"] = domain
        samples.append(data)
    return samples


async def _ensure_datasource(
    *,
    ds_repo: ChatbiDatasourceRepository,
    user_id: int,
    domain: str,
    db_name: str,
) -> int:
    name = f"BEAVER:{domain}"
    existing = await ds_repo.get_active_by_name_for_user(name, user_id)
    if existing is not None:
        return existing.id
    payload = ChatbiDatasourceCreateInput(
        user_id=user_id,
        name=name,
        connector_type="MYSQL",
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=db_name,
        schema_name=None,
        username=MYSQL_USER,
        password=MYSQL_PASSWORD,
        extra_params={},
        remark=f"BEAVER {domain} MySQL benchmark datasource",
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
    domain: str,
    mode: PreprocessMode,
) -> None:
    if mode == "skip":
        return

    if await task_repo.has_active_task(datasource_id):
        raise RuntimeError(
            f"数据源 {domain} (id={datasource_id}) 已有进行中的预处理任务"
        )

    if mode == "enqueue":
        record = await ds_service.enqueue_preprocess(
            ChatbiDatasourcePreprocessInput(
                user_id=user_id,
                datasource_id=datasource_id,
            ),
        )
        print(f"  [{domain}] 预处理已入队 task_id={record.task_id}")
        return

    task_id = await task_repo.create_task(
        datasource_id=datasource_id,
        task_type=TaskType.PREPROCESS_SCHEMA.value,
        user_id=user_id,
    )
    await unit_of_work.commit()
    print(f"  [{domain}] 预处理开始 task_id={task_id} ...")
    await ds_service.process_preprocess_task(task_id)
    task = await task_repo.get_task_for_update(task_id)
    if task is None or task.status != TaskStatus.SUCCESS.value:
        error = (task.last_error if task else None) or "未知错误"
        raise RuntimeError(f"数据源 {domain} (id={datasource_id}) 预处理失败: {error}")
    print(f"  [{domain}] 预处理完成")


async def import_beaver(
    *,
    user_id: int,
    preprocess_mode: PreprocessMode,
) -> None:
    settings = _settings()
    initialize_chatbi_vector_backend(build_chatbi_vector_settings(settings))

    root = Path(__file__).resolve().parents[2] / "BEAVER"
    samples = _load_samples(root)
    if not samples:
        print("没有找到任何样本")
        return

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
                dataset_code="BEAVER",
                display_name="BEAVER",
                description="BEAVER enterprise Text-to-SQL benchmark (MySQL)",
                current_version="DEV",
                user_id=user_id,
            )

            # 去重域 → datasource
            domains_seen: set[str] = set()
            datasource_by_domain: dict[str, int] = {}
            order = 0
            for sample in samples:
                domain = sample["_domain"]
                if domain in domains_seen:
                    continue
                domains_seen.add(domain)
                db_name = DOMAIN_DB_MAP[domain]
                datasource_id = await _ensure_datasource(
                    ds_repo=ds_repo,
                    user_id=user_id,
                    domain=domain,
                    db_name=db_name,
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
                        domain=domain,
                        mode=preprocess_mode,
                    )
                await benchmark_repo.upsert_dataset_datasource(
                    dataset_id=dataset_id,
                    datasource_id=datasource_id,
                    db_id=domain,
                    display_name=f"{domain} ({db_name})",
                    status="READY",
                    sort_order=order,
                    user_id=user_id,
                )
                datasource_by_domain[domain] = datasource_id
                order += 1

            # 插入样本
            for index, sample in enumerate(samples):
                domain = sample["_domain"]
                db_name = DOMAIN_DB_MAP[domain]
                gold_sql = str(sample.get("sql") or "")
                evidence = ""
                question = str(sample.get("question") or "")
                sample_id = sample.get("id", f"{domain}_{index}")

                await benchmark_repo.upsert_sample(
                    sample_code=f"BEAVER:{domain}:{sample_id}:{index}",
                    dataset_id=dataset_id,
                    dataset_version="DEV",
                    datasource_id=datasource_by_domain[domain],
                    db_id=domain,
                    source_group="dev",
                    question=question,
                    gold_sql=gold_sql,
                    evidence=evidence,
                    ref_json=build_reference_json(gold_sql, evidence),
                    user_id=user_id,
                )

            await benchmark_repo.refresh_dataset_datasource_counts(dataset_id)
            await benchmark_repo.refresh_dataset_counts(dataset_id, user_id=user_id)
            await unit_of_work.commit()
            print(f"\nImported BEAVER: dataset_id={dataset_id}, samples={len(samples)}, domains={len(datasource_by_domain)}")
    finally:
        await file_access.aclose()
        await database.dispose()


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
    parser = argparse.ArgumentParser(description="导入 BEAVER benchmark 数据 (MySQL)")
    parser.add_argument("--user-id", type=int, default=None, help="数据源和样本 owner 用户 ID")
    parser.add_argument(
        "--enqueue-only",
        action="store_true",
        help="仅创建预处理任务并投递 Redis",
    )
    parser.add_argument(
        "--skip-preprocess",
        action="store_true",
        help="跳过完整预处理，仅写入原始 db_schema",
    )
    args = parser.parse_args()
    user_id = _resolve_user_id(args.user_id)
    preprocess_mode = _resolve_preprocess_mode(
        enqueue_only=args.enqueue_only,
        skip_preprocess=args.skip_preprocess,
    )
    asyncio.run(
        import_beaver(
            user_id=user_id,
            preprocess_mode=preprocess_mode,
        )
    )


if __name__ == "__main__":
    main()
