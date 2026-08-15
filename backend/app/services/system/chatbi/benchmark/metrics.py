"""ChatBI benchmark 五项指标计算。"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from .sql_reference import extract_sql_reference

__all__ = [
    "compute_benchmark_metrics",
    "compute_set_f1",
]


def compute_benchmark_metrics(
    *,
    gold_sql: str,
    generated_sql: str,
    ref_json: dict[str, Any],
    gold_rows: list[dict[str, Any]],
    generated_rows: list[dict[str, Any]],
    db_schema: dict[str, Any] | None = None,
    dialect: str = "sqlite",
) -> tuple[dict[str, float], dict[str, Any]]:
    """计算 execution_accuracy 与四项结构 F1。"""

    gold_ref = extract_sql_reference(gold_sql, db_schema=db_schema, dialect=dialect)
    generated_ref = extract_sql_reference(
        generated_sql,
        db_schema=db_schema,
        dialect=dialect,
    )

    gold_tables = _prefer_parsed_or_ref(
        gold_ref.tables,
        ref_json,
        "gold_tables",
        "goldTables",
    )
    gold_columns = _prefer_parsed_or_ref(
        gold_ref.columns,
        ref_json,
        "gold_columns",
        "goldColumns",
    )
    gold_join_keys = _prefer_parsed_or_ref(
        gold_ref.join_keys,
        ref_json,
        "gold_join_keys",
        "goldJoinKeys",
    )
    gold_domain = _prefer_parsed_or_ref(
        gold_ref.constant_predicates,
        ref_json,
        "gold_domain_predicates",
        "goldDomainPredicates",
    )

    values = {
        "execution_accuracy": 1.0 if _results_match(gold_rows, generated_rows) else 0.0,
        "table_f1": compute_set_f1(gold_tables, generated_ref.tables),
        "column_f1": compute_set_f1(gold_columns, generated_ref.columns),
        "join_f1": compute_set_f1(gold_join_keys, generated_ref.join_keys),
        "domain_knowledge_f1": compute_set_f1(gold_domain, generated_ref.constant_predicates),
    }
    detail = {
        "gold_tables": gold_tables,
        "gold_columns": gold_columns,
        "gold_join_keys": gold_join_keys,
        "gold_constant_predicates": gold_domain,
        "generated_tables": list(generated_ref.tables),
        "generated_columns": list(generated_ref.columns),
        "generated_join_keys": list(generated_ref.join_keys),
        "generated_constant_predicates": list(generated_ref.constant_predicates),
        "parse_status": {
            "gold": gold_ref.parse_status,
            "generated": generated_ref.parse_status,
        },
        "result_compare": {"matched": values["execution_accuracy"] == 1.0},
    }
    return values, detail


def compute_set_f1(
    gold: list[str] | tuple[str, ...], generated: list[str] | tuple[str, ...]
) -> float:
    """集合 F1；元素比较前统一为大写（对齐 BEAVER eval）。"""

    gold_set = {_normalize_token(item) for item in gold if item}
    generated_set = {_normalize_token(item) for item in generated if item}
    if not gold_set and not generated_set:
        return 1.0
    if not gold_set or not generated_set:
        return 0.0
    tp = len(gold_set & generated_set)
    precision = tp / len(generated_set)
    recall = tp / len(gold_set)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _normalize_token(value: str) -> str:
    return " ".join(value.upper().split())


def _ref_list(ref_json: dict[str, Any], key: str, *legacy_keys: str) -> list[str]:
    raw = ref_json.get(key)
    if not isinstance(raw, list):
        for legacy_key in legacy_keys:
            raw = ref_json.get(legacy_key)
            if isinstance(raw, list):
                break
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item is not None and str(item).strip()]


def _prefer_parsed_or_ref(
    parsed: tuple[str, ...],
    ref_json: dict[str, Any],
    key: str,
    *legacy_keys: str,
) -> list[str]:
    if parsed:
        return list(parsed)
    return _ref_list(ref_json, key, *legacy_keys)


def _normalize_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Decimal):
        return round(float(value), 6)
    return str(value) if not isinstance(value, int | bool) else value


def _row_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    values = [_normalize_cell(value) for value in row.values()]
    return tuple(sorted(values, key=_sort_key))


def _sort_key(value: Any) -> tuple[str, str]:
    if value is None:
        return ("0", "")
    return ("1", str(value))


def _results_match(gold_rows: list[dict[str, Any]], generated_rows: list[dict[str, Any]]) -> bool:
    if len(gold_rows) != len(generated_rows):
        return False
    return Counter(_row_signature(row) for row in gold_rows) == Counter(
        _row_signature(row) for row in generated_rows
    )
