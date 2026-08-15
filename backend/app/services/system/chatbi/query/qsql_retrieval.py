"""DAIL-SQL inspired Q-SQL retrieval helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .....domain.system.chatbi import ChatbiQsqlRecord
from .....domain.system.chatbi.qsql import QSQL_SCOPE_GLOBAL

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")
_VALUE_PATTERN = re.compile(
    r"('([^']|'')*'|\"([^\"]|\"\")*\"|\b\d+(?:\.\d+)?\b)",
    flags=re.IGNORECASE,
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

_QSQL_DAIL_VECTOR_WEIGHT = 0.55
_QSQL_DAIL_LEXICAL_WEIGHT = 0.25
_QSQL_DAIL_SKELETON_WEIGHT = 0.20


@dataclass(frozen=True, slots=True)
class GlobalQsqlScopeFilter:
    source_dataset: str
    source_db_id: str


@dataclass(frozen=True, slots=True)
class QsqlRetrievalCandidate:
    record: ChatbiQsqlRecord
    vector_score: float


@dataclass(frozen=True, slots=True)
class RankedQsqlExample:
    record: ChatbiQsqlRecord
    score: float
    vector_score: float
    lexical_score: float
    skeleton_score: float


def global_qsql_matches_scope(
    record: ChatbiQsqlRecord,
    *,
    scope_filter: GlobalQsqlScopeFilter | None,
) -> bool:
    """GLOBAL 样例仅在 source_dataset + source_db_id 匹配时保留。"""
    if (record.scope or QSQL_SCOPE_GLOBAL) != QSQL_SCOPE_GLOBAL:
        return True
    if scope_filter is None:
        return True
    dataset = (record.source_dataset or "").strip().upper()
    db_id = (record.source_db_id or "").strip()
    return (
        dataset == scope_filter.source_dataset.strip().upper()
        and db_id == scope_filter.source_db_id.strip()
    )


def rank_qsql_candidates(
    *,
    question: str,
    candidates: list[QsqlRetrievalCandidate],
    top_k: int,
) -> list[RankedQsqlExample]:
    question_tokens = _text_tokens(question)
    question_features = _question_skeleton_features(question)
    ranked: list[RankedQsqlExample] = []
    for candidate in candidates:
        record = candidate.record
        lexical_score = _jaccard(question_tokens, _text_tokens(record.question))
        skeleton_score = _skeleton_score(
            question_features,
            _sql_skeleton_features(record.sql_skeleton or _sql_to_skeleton(record.sql_body)),
        )
        vector_score = _normalize_vector_score(candidate.vector_score)
        score = (
            _QSQL_DAIL_VECTOR_WEIGHT * vector_score
            + _QSQL_DAIL_LEXICAL_WEIGHT * lexical_score
            + _QSQL_DAIL_SKELETON_WEIGHT * skeleton_score
        )
        ranked.append(
            RankedQsqlExample(
                record=record,
                score=score,
                vector_score=vector_score,
                lexical_score=lexical_score,
                skeleton_score=skeleton_score,
            )
        )
    ranked.sort(key=lambda item: item.score, reverse=True)
    return _dedupe_ranked(ranked, top_k=top_k)


def build_sql_skeleton_from_tokens(tokens: list[object]) -> str:
    return _compact_sql_skeleton(" ".join(str(item).lower() for item in tokens))


def build_sql_skeleton_from_sql(sql: str) -> str:
    return _sql_to_skeleton(sql)


def _dedupe_ranked(items: list[RankedQsqlExample], *, top_k: int) -> list[RankedQsqlExample]:
    selected: list[RankedQsqlExample] = []
    seen_sql: set[str] = set()
    for item in items:
        key = _normalize_sql_key(item.record.sql_body)
        if key in seen_sql:
            continue
        seen_sql.add(key)
        selected.append(item)
        if len(selected) >= top_k:
            break
    return selected


def _text_tokens(text: str) -> set[str]:
    tokens = {
        token
        for token in (match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text or ""))
        if token and token not in _STOPWORDS
    }
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _normalize_vector_score(score: float) -> float:
    value = float(score)
    if value < 0.0:
        value = (value + 1.0) / 2.0
    return max(0.0, min(1.0, value))


def _question_skeleton_features(question: str) -> set[str]:
    text = (question or "").lower()
    features = {"select"}
    if _has_any(
        text,
        ("how many", "number of", "count", "\u591a\u5c11", "\u6570\u91cf", "\u51e0\u4e2a"),
    ):
        features.add("agg:count")
    if _has_any(text, ("average", "avg", "mean", "\u5e73\u5747")):
        features.add("agg:avg")
    if _has_any(text, ("sum", "total", "\u5408\u8ba1", "\u603b\u8ba1", "\u603b\u548c")):
        features.add("agg:sum")
    if _has_any(
        text,
        ("maximum", "max", "highest", "largest", "\u6700\u591a", "\u6700\u9ad8", "\u6700\u5927"),
    ):
        features.add("agg:max")
        features.add("order")
    if _has_any(
        text,
        ("minimum", "min", "lowest", "smallest", "\u6700\u5c11", "\u6700\u4f4e", "\u6700\u5c0f"),
    ):
        features.add("agg:min")
        features.add("order")
    if _has_any(text, ("top", "first", "last", "rank", "\u524d", "\u6392\u540d")):
        features.add("order")
        features.add("limit")
    if _has_any(text, ("each", "per", "group by", "by ", "\u6309", "\u6bcf")):
        features.add("group")
    if _has_any(
        text,
        (
            "where",
            "older than",
            "greater than",
            "less than",
            "between",
            "over",
            "under",
            "\u8d85\u8fc7",
            "\u5927\u4e8e",
            "\u5c0f\u4e8e",
            "\u4e4b\u95f4",
            "\u4e3a",
            "\u662f",
        ),
    ):
        features.add("where")
    if _has_any(text, (" and ", " or ", "\u4e14", "\u6216")):
        features.add("logic")
    return features


def _sql_skeleton_features(skeleton: str) -> set[str]:
    text = f" {_compact_sql_skeleton(skeleton)} "
    features = set()
    if " select " in text:
        features.add("select")
    if " where " in text:
        features.add("where")
    if " group by " in text:
        features.add("group")
    if " having " in text:
        features.add("having")
    if " order by " in text:
        features.add("order")
    if " limit " in text:
        features.add("limit")
    if " join " in text:
        features.add("join")
    if " distinct " in text:
        features.add("distinct")
    if any(op in text for op in (" union ", " intersect ", " except ")):
        features.add("setop")
    for agg in ("count", "sum", "avg", "max", "min"):
        if f" {agg} " in text or f" {agg} ( " in text:
            features.add(f"agg:{agg}")
    if any(op in text for op in (" and ", " or ")):
        features.add("logic")
    return features


def _skeleton_score(question_features: set[str], sql_features: set[str]) -> float:
    if not question_features or not sql_features:
        return 0.0
    return len(question_features & sql_features) / len(question_features | sql_features)


def _sql_to_skeleton(sql: str) -> str:
    return _compact_sql_skeleton(_VALUE_PATTERN.sub(" value ", (sql or "").lower()))


def _compact_sql_skeleton(sql: str) -> str:
    return " ".join((sql or "").replace(",", " , ").replace("(", " ( ").replace(")", " ) ").split())


def _normalize_sql_key(sql: str) -> str:
    return re.sub(r"\s+", " ", (sql or "").strip().lower())


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(item in text for item in needles)


__all__ = [
    "GlobalQsqlScopeFilter",
    "QsqlRetrievalCandidate",
    "RankedQsqlExample",
    "build_sql_skeleton_from_sql",
    "build_sql_skeleton_from_tokens",
    "global_qsql_matches_scope",
    "rank_qsql_candidates",
]
