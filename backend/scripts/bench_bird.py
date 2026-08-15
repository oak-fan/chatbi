"""Run BIRD MiniDev benchmarks from the standalone cogmait-chatbi project.

The script is intentionally self-contained so experiments do not depend on
cogmait-backend-v2 runner paths or environment bootstrapping.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - optional for minimal envs
    yaml = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRESETS_FILE = PROJECT_ROOT / "scripts" / "experiment_presets.yaml"
BACKEND_ENV_FALLBACK = PROJECT_ROOT.parent / "cogmait-backend-v2" / ".env"
sys.path.insert(0, str(PROJECT_ROOT))


def _load_preset(name: str) -> dict[str, Any]:
    if yaml is None:
        raise SystemExit("PyYAML is required for --preset; install pyyaml in .venv")
    if not PRESETS_FILE.is_file():
        raise SystemExit(f"Preset file not found: {PRESETS_FILE}")
    presets = yaml.safe_load(PRESETS_FILE.read_text(encoding="utf-8")) or {}
    preset = presets.get(name)
    if not isinstance(preset, dict):
        raise SystemExit(f"Unknown preset: {name}")
    return preset


def _apply_preset(args: argparse.Namespace) -> None:
    if not args.preset:
        return
    preset = _load_preset(args.preset)
    args.evidence = True
    for key, value in preset.items():
        if key == "description":
            continue
        attr = key.replace("-", "_")
        if hasattr(args, attr):
            if attr == "candidate_paths" and isinstance(value, str):
                value = _parse_candidate_paths(value)
            setattr(args, attr, value)


def _load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
def _read_env_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'") or None
    return None

def _load_backend_fallback_env() -> None:
    if not BACKEND_ENV_FALLBACK.is_file():
        return
    allowed = {
        "DEFAULT_COMPLETION_MODEL",
        "DEFAULT_EMBEDDING_MODEL",
        "DEFAULT_RERANK_MODEL",
        "CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY",
    }
    for line in BACKEND_ENV_FALLBACK.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in allowed and value and not os.environ.get(key):
            os.environ[key] = value

def _bootstrap_env() -> None:
    _load_env_file(PROJECT_ROOT / ".env")
    _load_env_file(PROJECT_ROOT / ".env.local", override=True)
    _load_backend_fallback_env()
    os.environ["OBSERVABILITY_PROVIDER"] = os.environ.get(
        "CHATBI_EXPERIMENT_OBSERVABILITY_PROVIDER",
        "noop",
    )
    os.environ.setdefault("DEFAULT_USER_ID", "1")
    bird_root = PROJECT_ROOT.parent / "BIRD-MINIDEV"
    if bird_root.is_dir():
        os.environ.setdefault("CHATBI_BIRD_MINIDEV_ROOT", str(bird_root))
    if os.environ.get("REDIS_KEY_PREFIX"):
        os.environ["REDIS_KEY_PREFIX"] = os.environ["REDIS_KEY_PREFIX"].strip()


async def _enrich_env_from_sys_config() -> None:
    async def fetch_from_url(url: str | None) -> None:
        if not url:
            return
        import asyncpg

        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            keys = (
                "ai.default_completion_model",
                "ai.default_embedding_model",
                "ai.default_rerank_model",
                "chatbi.datasource_credential_encryption_key",
            )
            rows = await conn.fetch(
                "SELECT config_key, config_value FROM sys_config WHERE config_key = ANY($1::text[])",
                list(keys),
            )
        finally:
            await conn.close()

        mapping = {
            "ai.default_completion_model": "DEFAULT_COMPLETION_MODEL",
            "ai.default_embedding_model": "DEFAULT_EMBEDDING_MODEL",
            "ai.default_rerank_model": "DEFAULT_RERANK_MODEL",
            "chatbi.datasource_credential_encryption_key": (
                "CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY"
            ),
        }
        for row in rows:
            env_key = mapping.get(row["config_key"])
            if env_key and row["config_value"] and not os.environ.get(env_key):
                os.environ[env_key] = str(row["config_value"])

    await fetch_from_url(os.environ.get("DATABASE_URL"))
    if not os.environ.get("CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY"):
        backend_env = _read_env_value(BACKEND_ENV_FALLBACK, "DATABASE_URL")
        if backend_env and backend_env != os.environ.get("DATABASE_URL"):
            await fetch_from_url(backend_env)
    if not os.environ.get("CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY"):
        # Same default as _import_bird.sh; BIRD SQLite credentials were encrypted with it.
        os.environ["CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY"] = "benchmark-dev-key-2026"

def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        return {key: _json_default(value) for key, value in asdict(obj).items()}
    if isinstance(obj, dict):
        return {key: _json_default(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_json_default(value) for value in obj]
    return obj


def _pick_bird_dataset(datasets: list[Any], dataset_code: str | None = None) -> Any | None:
    requested_code = (dataset_code or "").strip().upper()
    if requested_code:
        for dataset in datasets:
            if (dataset.dataset_code or "").upper() == requested_code:
                return dataset
        return None
    for dataset in datasets:
        code = (dataset.dataset_code or "").upper()
        name = (dataset.display_name or "").upper()
        if code == "BIRD" and ("MINIDEV" in name or "DEV" in name):
            return dataset
    for dataset in datasets:
        if (dataset.dataset_code or "").upper() == "BIRD":
            return dataset
    return None


async def _build_service(session: Any) -> Any:
    from cogmait_shared.db import UnitOfWork

    from app.core.redis import get_redis_client
    from app.observability import get_default_observability_provider
    from app.services.system.chatbi.benchmark_service import ChatbiBenchmarkService
    from app.services.system.llm_service import get_default_llm_service
    from app.services.system.rewrite import RewriteService

    llm_service = get_default_llm_service()
    return ChatbiBenchmarkService(
        unit_of_work=UnitOfWork(session),
        redis=get_redis_client(),
        llm_service=llm_service,
        rewrite_service=RewriteService(
            llm_service=llm_service,
            observability=get_default_observability_provider(),
        ),
    )


async def _noop_publish(*_args: Any, **_kwargs: Any) -> None:
    return None


def _print_sample_progress(
    *,
    run_id: int,
    sample_id: int | None,
    sample_code: str | None,
    status: str,
    processed_count: int,
    total_count: int,
    success_count: int,
    failed_count: int,
    elapsed_ms: int | None = None,
    remaining: int | None = None,
    concurrency: int | None = None,
    **_extra: Any,
) -> None:
    if status == "START":
        parts = [
            f"[bench] start process_run run_id={run_id}",
            f"done={processed_count}/{total_count}",
            f"ok={success_count}",
            f"fail={failed_count}",
        ]
        if remaining is not None:
            parts.append(f"remaining={remaining}")
        if concurrency is not None:
            parts.append(f"concurrency={concurrency}")
        print(" ".join(parts), flush=True)
        return

    pct = (100.0 * processed_count / total_count) if total_count else 0.0
    parts = [
        f"[bench] progress {processed_count}/{total_count} ({pct:.1f}%)",
        f"sample={sample_code or sample_id}",
        f"status={status}",
        f"ok={success_count}",
        f"fail={failed_count}",
    ]
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={elapsed_ms}")
    print(" ".join(parts), flush=True)


def _parse_candidate_paths(value: str) -> list[str]:
    paths = [item.strip() for item in value.split(",") if item.strip()]
    if not paths:
        raise argparse.ArgumentTypeError("candidate paths cannot be empty")
    return paths


def _build_method_config(args: argparse.Namespace) -> Any:
    from app.domain.system.chatbi import BenchmarkMethodConfig

    return BenchmarkMethodConfig(
        evidence_enabled=True,
        schema_selection_enabled=args.schema_selection,
        qsql_recall_enabled=args.qsql_recall,
        business_knowledge_recall_enabled=args.business_knowledge,
        sql_fix_enabled=args.sql_fix,
        rewrite_enabled=args.rewrite_enabled,
        summary_enabled=args.summary_enabled,
        sql_candidate_paths=args.candidate_paths,
        sql_selection_enabled=args.sql_selection,
        sql_validate_enabled=args.sql_validate,
        schema_top_k=args.schema_top_k,
        schema_full_if_small=args.schema_full_if_small,
        schema_small_table_threshold=args.schema_small_table_threshold,
        sql_fix_max_attempts=args.sql_fix_max_attempts,
        value_founding_enabled=args.value_founding,
        rag_enabled=args.rag,
        group_by_audit_enabled=args.group_by_audit,
        model=args.model or "default",
    )


async def _probe() -> dict[str, Any]:
    _bootstrap_env()
    await _enrich_env_from_sys_config()
    from app.core.config import get_settings
    from app.core.database import get_default_database

    get_settings.cache_clear()
    settings = get_settings()
    database = get_default_database()
    database.initialize()
    output: dict[str, Any] = {
        "settings": {
            "has_completion_model": bool(settings.default_completion_model),
            "has_embedding_model": bool(settings.default_embedding_model),
            "has_chatbi_key": bool(settings.chatbi_datasource_credential_encryption_key),
            "litellm_api_base_set": bool(settings.litellm_api_base),
        }
    }
    try:
        async with database.get_session() as session:
            service = await _build_service(session)
            datasets = await service.list_datasets()
            output["datasets"] = [_json_default(item) for item in datasets]
    finally:
        await database.dispose()
    return output


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    _bootstrap_env()
    await _enrich_env_from_sys_config()

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.core.database import get_default_database
    from app.domain.system.chatbi import (
        BenchmarkCaseListParams,
        BenchmarkMethodType,
        BenchmarkRunCreateInput,
    )

    settings = get_settings()
    database = get_default_database()
    database.initialize()
    user_id = args.user_id or int(os.environ.get("DEFAULT_USER_ID") or settings.default_user_id)

    output: dict[str, Any] = {
        "settings": {
            "has_completion_model": bool(settings.default_completion_model),
            "has_embedding_model": bool(settings.default_embedding_model),
            "has_chatbi_key": bool(settings.chatbi_datasource_credential_encryption_key),
            "litellm_api_base_set": bool(settings.litellm_api_base),
        },
        "args": vars(args),
    }
    try:
        async with database.get_session() as session:
            service = await _build_service(session)
            if args.skip_publish:
                service._publish_run = _noop_publish  # type: ignore[method-assign]

            if args.resume_run_id is not None:
                run = await service.resume_run(run_id=args.resume_run_id, user_id=user_id)
                run_id = run.id
                output["resumed_run"] = _json_default(run)
                _write_run_id_file(args.run_id_file, run_id, meta={
                    "dataset_code": run.dataset_code,
                    "preset": args.preset,
                    "total_count": run.total_count,
                    "processed_count": run.processed_count,
                    "phase": "resumed",
                })
                if str(run.status).upper() == "SUCCESS":
                    output["run"] = _json_default(run)
                    metrics = (
                        await service.get_run_detail(run_id=run_id, user_id=user_id)
                    )[1]
                    cases, total = await service.list_cases(
                        BenchmarkCaseListParams(
                            run_id=run_id,
                            user_id=user_id,
                            page=1,
                            size=args.case_page_size,
                        )
                    )
                    output["metrics"] = [_json_default(item) for item in metrics]
                    output["cases"] = [_json_default(item) for item in cases]
                    output["case_total"] = total
                    return output
            else:
                datasets = await service.list_datasets()
                dataset = _pick_bird_dataset(datasets, args.dataset_code)
                output["datasets"] = [_json_default(item) for item in datasets]
                if dataset is None:
                    raise SystemExit("BIRD dataset not found")
                output["selected_dataset"] = _json_default(dataset)

                payload = BenchmarkRunCreateInput(
                    user_id=user_id,
                    dataset_id=dataset.id,
                    method_type=BenchmarkMethodType.LUOSHU_CHATBI.value,
                    method_config=_build_method_config(args),
                    selected_datasource_ids=args.datasource_ids,
                    source_group=args.source_group,
                    sample_limit=None if args.sample_ids else args.limit,
                    sample_ids=args.sample_ids,
                    concurrency=args.concurrency,
                    timeout_seconds=args.timeout,
                )
                run = await service.create_run(payload)
                run_id = run.id
                output["created_run"] = _json_default(run)
                _write_run_id_file(args.run_id_file, run_id, meta={
                    "dataset_code": dataset.dataset_code,
                    "preset": args.preset,
                    "total_count": run.total_count,
                    "phase": "created",
                })

        async with database.get_session() as session:
            service = await _build_service(session)
            if args.skip_publish:
                service._publish_run = _noop_publish  # type: ignore[method-assign]
            service._on_sample_progress = _print_sample_progress
            await service.process_run(run_id)

        async with database.get_session() as session:
            service = await _build_service(session)
            run, metrics = await service.get_run_detail(run_id=run_id, user_id=user_id)
            cases, total = await service.list_cases(
                BenchmarkCaseListParams(
                    run_id=run_id,
                    user_id=user_id,
                    page=1,
                    size=args.case_page_size,
                )
            )
            output["run"] = _json_default(run)
            output["metrics"] = [_json_default(item) for item in metrics]
            output["cases"] = [_json_default(item) for item in cases]
            output["case_total"] = total
    finally:
        await database.dispose()

    return output


def _write_output(output: dict[str, Any], output_path: Path | None) -> Path:
    if output_path is None:
        run_id = output.get("run", {}).get("id") or output.get("created_run", {}).get("id")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = PROJECT_ROOT / "artifacts" / "benchmarks" / f"bird_{timestamp}_{run_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return output_path


def _metric_value(output: dict[str, Any], name: str) -> float | None:
    for metric in output.get("metrics") or []:
        if metric.get("metric_name") == name:
            value = metric.get("metric_value")
            return None if value is None else float(value)
    return None


def _wrong_sample_ids_from_artifact(path: Path) -> list[int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids: list[int] = []
    for case in payload.get("cases") or []:
        status = str(case.get("status") or "").upper()
        if status != "SUCCESS":
            continue
        ex = case.get("execution_accuracy")
        try:
            if float(ex or 0) >= 1.0:
                continue
        except (TypeError, ValueError):
            pass
        sample_id = case.get("sample_id")
        if sample_id is not None:
            ids.append(int(sample_id))
    return ids


def _write_run_id_file(path: Path | None, run_id: int, *, meta: dict[str, Any] | None = None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": int(run_id),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **(meta or {}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[bench] wrote run_id={run_id} -> {path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a standalone ChatBI BIRD benchmark")
    parser.add_argument("--preset", default=None, help="Load config from experiment_presets.yaml")
    parser.add_argument("--probe", action="store_true", help="Check DB/dataset readiness only")
    parser.add_argument("--dataset-code", default=None, help="benchmark dataset code to run")
    parser.add_argument(
        "--resume-run-id",
        type=int,
        default=None,
        help="resume an existing benchmark run by id (skip create)",
    )
    parser.add_argument(
        "--run-id-file",
        type=Path,
        default=PROJECT_ROOT / "scripts" / "bench_resume_state.json",
        help="write run_id JSON here as soon as the run is created/resumed",
    )
    parser.add_argument("--limit", type=int, default=100, help="sample limit")
    parser.add_argument(
        "--sample-ids",
        type=int,
        nargs="*",
        default=None,
        help="run only these benchmark sample ids",
    )
    parser.add_argument(
        "--wrong-from-artifact",
        type=Path,
        default=None,
        help="reuse WRONG_RESULT sample ids from a prior artifact JSON",
    )
    parser.add_argument("--timeout", type=int, default=180, help="per-sample timeout seconds")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--source-group", default=None)
    parser.add_argument("--datasource-ids", type=int, nargs="*", default=None)
    parser.add_argument("--case-page-size", type=int, default=100)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--skip-publish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="skip Redis task publish; the script processes the run synchronously",
    )

    parser.add_argument("--evidence", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--candidate-paths",
        type=_parse_candidate_paths,
        default=_parse_candidate_paths(
            "ddl:chain_of_thought,ddl:direct,ddl:problem_decomposition"
        ),
        help="Comma-separated schema:prompt candidate paths",
    )
    parser.add_argument("--schema-selection", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--qsql-recall", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--business-knowledge", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--sql-fix", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--sql-selection", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--sql-validate", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--rag", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--value-founding", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--group-by-audit", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--rewrite-enabled", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--summary-enabled", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--schema-top-k", type=int, default=None)
    parser.add_argument("--schema-full-if-small", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--schema-small-table-threshold", type=int, default=15)
    parser.add_argument("--sql-fix-max-attempts", type=int, default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    _apply_preset(args)
    args.evidence = True
    if args.wrong_from_artifact is not None:
        wrong_ids = _wrong_sample_ids_from_artifact(args.wrong_from_artifact)
        if not wrong_ids:
            raise SystemExit(f"No WRONG_RESULT samples in {args.wrong_from_artifact}")
        args.sample_ids = wrong_ids
        args.limit = len(wrong_ids)

    if args.probe:
        print(json.dumps(asyncio.run(_probe()), ensure_ascii=False, indent=2))
        return

    output = asyncio.run(_run(args))
    path = _write_output(output, args.output)
    summary = {
        "run_id": output.get("run", {}).get("id"),
        "status": output.get("run", {}).get("status"),
        "total_count": output.get("run", {}).get("total_count"),
        "processed_count": output.get("run", {}).get("processed_count"),
        "execution_accuracy": _metric_value(output, "execution_accuracy"),
        "valid_sql_rate": _metric_value(output, "valid_sql_rate"),
        "execution_error_rate": _metric_value(output, "execution_error_rate"),
        "output": str(path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()



