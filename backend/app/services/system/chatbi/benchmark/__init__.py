"""ChatBI benchmark 指标与 SQL 解析。"""

from .metrics import compute_benchmark_metrics, compute_set_f1
from .question import build_benchmark_question
from .sql_reference import (
    SqlReference,
    build_reference_json,
    connector_type_to_dialect,
    extract_sql_reference,
)

__all__ = [
    "SqlReference",
    "build_benchmark_question",
    "build_reference_json",
    "compute_benchmark_metrics",
    "compute_set_f1",
    "connector_type_to_dialect",
    "extract_sql_reference",
]
