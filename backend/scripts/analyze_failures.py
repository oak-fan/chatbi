"""Analyze ChatBI BIRD benchmark artifacts and summarize failure modes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "benchmarks"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_artifact() -> Path:
    files = sorted(ARTIFACT_DIR.glob("bird_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No artifacts under {ARTIFACT_DIR}")
    return files[-1]


def _find_artifact(*, run_id: str | None, path: Path | None) -> Path:
    if path is not None:
        return path
    if run_id:
        matches = list(ARTIFACT_DIR.glob(f"bird_*_{run_id}.json"))
        if not matches:
            raise SystemExit(f"No artifact for run_id={run_id}")
        return matches[-1]
    return _latest_artifact()


def _classify_case(case: dict[str, Any]) -> str:
    status = str(case.get("status") or "").upper()
    if status == "TIMEOUT":
        return "TIMEOUT"
    if status in {"EXEC_ERROR", "PARSE_ERROR"}:
        return status
    if status != "SUCCESS":
        return status or "UNKNOWN"
    metrics = case.get("metric_values") or {}
    ex = metrics.get("execution_accuracy")
    if ex is None:
        ex = case.get("execution_accuracy")
    try:
        if float(ex or 0) >= 1.0:
            return "CORRECT"
    except (TypeError, ValueError):
        pass
    return "WRONG_RESULT"


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases") or []
    counts = Counter(_classify_case(case) for case in cases)
    wrong = [case for case in cases if _classify_case(case) == "WRONG_RESULT"]
    wrong_preview = [
        {
            "sample_id": case.get("sample_id"),
            "question": (case.get("question") or "")[:120],
            "generated_sql": (case.get("generated_sql") or "")[:200],
            "gold_sql": (case.get("gold_sql") or "")[:200],
        }
        for case in wrong[:20]
    ]
    metrics = {
        item.get("metric_name"): item.get("metric_value")
        for item in (payload.get("metrics") or [])
    }
    return {
        "run_id": (payload.get("run") or {}).get("id"),
        "status": (payload.get("run") or {}).get("status"),
        "processed_count": (payload.get("run") or {}).get("processed_count"),
        "execution_accuracy": metrics.get("execution_accuracy"),
        "valid_sql_rate": metrics.get("valid_sql_rate"),
        "execution_error_rate": metrics.get("execution_error_rate"),
        "timeout_rate": metrics.get("timeout_rate"),
        "case_counts": dict(counts),
        "wrong_samples_preview": wrong_preview,
        "method_config": (payload.get("run") or {}).get("method_config_snapshot"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze benchmark artifact JSON")
    parser.add_argument("--latest", action="store_true", help="Analyze newest artifact")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--path", type=Path, default=None)
    args = parser.parse_args()

    artifact = _find_artifact(run_id=args.run_id, path=args.path)
    summary = analyze(_load_json(artifact))
    summary["artifact"] = str(artifact)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
