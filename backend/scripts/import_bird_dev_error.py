"""从 待导入错误样本/ 目录中导入每个 CSV 文件中的错误样本为独立的样本集。

每个 CSV 文件的文件名（不含后缀）用作 dataset_code。

用法：
  python scripts/import_bird_dev_error.py --user-id 1
  python scripts/import_bird_dev_error.py --user-id 1 --csv-dir /path/to/待导入错误样本
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import Any

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

def _configure_snowflake_generator(*, datacenter_id: int, worker_id: int) -> None:
    from time import monotonic_ns, time

    from cogmait_shared.core.id_generator import configure_snowflake_generator

    start_wall_ms = int(time() * 1000)
    start_monotonic_ms = monotonic_ns() // 1_000_000

    def current_time_millis() -> int:
        return start_wall_ms + (monotonic_ns() // 1_000_000 - start_monotonic_ms)

    configure_snowflake_generator(
        datacenter_id=datacenter_id,
        worker_id=worker_id,
        time_provider=current_time_millis,
    )


from app.core.config import get_settings
from app.core.database import get_default_database
from app.repositories.system.chatbi import ChatbiBenchmarkRepository
from app.services.system.chatbi.benchmark import build_reference_json
from cogmait_shared.db import UnitOfWork

DEFAULT_CSV_DIR = PROJECT_ROOT / "待导入错误样本"


def _parse_question_evidence(raw: str) -> tuple[str, str | None]:
    parts = raw.split("# Evidence", 1)
    question = parts[0].strip()
    evidence = parts[1].strip() if len(parts) > 1 else None
    return question, evidence


def _load_samples(csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")

    samples: list[dict[str, Any]] = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db_id = (row.get("数据库名称") or "").strip()
            gold_sql = (row.get("gold_sql") or "").strip()
            if not db_id or not gold_sql:
                continue
            question_field = (row.get("问题") or "").strip()
            question, evidence = _parse_question_evidence(question_field)
            samples.append(
                {
                    "db_id": db_id,
                    "question": question,
                    "gold_sql": gold_sql,
                    "evidence": evidence,
                    "error_type": (row.get("错误类型") or "").strip(),
                    "error_reason": (row.get("错误原因") or "").strip(),
                }
            )
    return samples


async def import_one_csv(
    *,
    user_id: int,
    csv_path: Path,
    dataset_code: str,
    benchmark_repo: ChatbiBenchmarkRepository,
    datasource_by_db: dict[str, int],
) -> None:
    samples = _load_samples(csv_path)
    if not samples:
        print(f"  [{dataset_code}] CSV 中无有效样本，跳过")
        return
    print(f"  [{dataset_code}] 加载了 {len(samples)} 个错误样本")

    dataset_id = await benchmark_repo.upsert_dataset(
        dataset_code=dataset_code,
        display_name=dataset_code,
        description=f"从 {csv_path.name} 导入的错误样本",
        current_version="DEV",
        user_id=user_id,
    )
    print(f"  [{dataset_code}] 创建样本集 dataset_id={dataset_id}")

    # 收集该 CSV 实际用到的 db_id，为它们创建 dataset_datasource 关联
    used_db_ids = {item["db_id"] for item in samples}
    for order, db_id in enumerate(sorted(used_db_ids)):
        datasource_id = datasource_by_db.get(db_id)
        if datasource_id is None:
            continue
        await benchmark_repo.upsert_dataset_datasource(
            dataset_id=dataset_id,
            datasource_id=datasource_id,
            db_id=db_id,
            display_name=db_id,
            status="READY",
            sort_order=order,
            user_id=user_id,
        )

    imported = 0
    skipped = 0
    for index, item in enumerate(samples):
        db_id = item["db_id"]
        gold_sql = item["gold_sql"]
        evidence = item["evidence"]

        datasource_id = datasource_by_db.get(db_id)
        if datasource_id is None:
            print(f"    [!] 跳过未知数据库: {db_id}")
            skipped += 1
            continue

        await benchmark_repo.upsert_sample(
            sample_code=f"{db_id}:error:{index}",
            dataset_id=dataset_id,
            dataset_version="DEV",
            datasource_id=datasource_id,
            db_id=db_id,
            source_group="error",
            question=item["question"],
            gold_sql=gold_sql,
            evidence=evidence,
            ref_json=build_reference_json(gold_sql, evidence),
            user_id=user_id,
        )
        imported += 1

    await benchmark_repo.refresh_dataset_datasource_counts(dataset_id)
    await benchmark_repo.refresh_dataset_counts(dataset_id, user_id=user_id)

    print(f"  [{dataset_code}] 导入完成: 成功 {imported}, 跳过 {skipped}, 总计 {len(samples)}")


async def import_bird_dev_error(*, user_id: int, csv_dir: Path = DEFAULT_CSV_DIR) -> None:
    settings = get_settings()
    _configure_snowflake_generator(
        datacenter_id=settings.snowflake_datacenter_id,
        worker_id=settings.snowflake_worker_id,
    )

    if not csv_dir.is_dir():
        print(f"目录不存在: {csv_dir}")
        return

    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        print(f"目录中无 CSV 文件: {csv_dir}")
        return

    database = get_default_database()
    database.initialize()

    try:
        async with database.get_session() as session:
            unit_of_work = UnitOfWork(session)
            benchmark_repo = ChatbiBenchmarkRepository(session)

            bird_dev_dataset = await benchmark_repo.get_dataset_by_code("BIRD-DEV")
            if bird_dev_dataset is None:
                raise RuntimeError("BIRD-DEV 数据集不存在，请先运行 import_bird_dev.py")

            datasources = await benchmark_repo.list_dataset_datasources(
                bird_dev_dataset.id
            )
            datasource_by_db: dict[str, int] = {
                ds.db_id: ds.datasource_id for ds in datasources
            }
            print(f"找到了 {len(datasource_by_db)} 个数据源映射")
            print(f"发现 {len(csv_files)} 个 CSV 文件\n")

            for csv_path in csv_files:
                dataset_code = csv_path.stem
                await import_one_csv(
                    user_id=user_id,
                    csv_path=csv_path,
                    dataset_code=dataset_code,
                    benchmark_repo=benchmark_repo,
                    datasource_by_db=datasource_by_db,
                )
                print()

            await unit_of_work.commit()

            import os
            db_url = os.getenv('DATABASE_URL', '未设置')
            if '://' in db_url and '@' in db_url:
                parts = db_url.split('@')
                if '://' in parts[0]:
                    protocol_auth = parts[0].split('://')
                    if len(protocol_auth) == 2:
                        db_url = f"{protocol_auth[0]}://****:****@{parts[1]}"
            print(f"全部导入完成，数据库连接: {db_url}")
    finally:
        await database.dispose()


def _resolve_user_id(raw: int | None) -> int:
    if raw is not None:
        return raw
    configured = get_settings().chatbi_benchmark_import_user_id
    if configured is not None:
        return configured
    raise SystemExit(
        "请通过 --user-id 或 CHATBI_BENCHMARK_IMPORT_USER_ID 指定导入数据 owner 用户 ID"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="从 待导入错误样本/ 目录导入错误样本为独立的样本集")
    parser.add_argument("--user-id", type=int, default=None, help="样本 owner 用户 ID")
    parser.add_argument(
        "--csv-dir",
        default=None,
        help="待导入错误样本目录路径（默认: 项目根目录/待导入错误样本）",
    )
    args = parser.parse_args()
    user_id = _resolve_user_id(args.user_id)
    csv_dir = Path(args.csv_dir).resolve() if args.csv_dir else DEFAULT_CSV_DIR
    asyncio.run(import_bird_dev_error(user_id=user_id, csv_dir=csv_dir))


if __name__ == "__main__":
    main()
