"""Candidate grouping and fallback selection for Agentar-style SQL scaling."""

from __future__ import annotations

import re

from .types import SqlCandidate, SqlCandidateGroup

_SPACE_PATTERN = re.compile(r"\s+")


def dedupe_sql_candidates(candidates: list[SqlCandidate]) -> list[SqlCandidate]:
    """Remove duplicate SQL strings while preserving generation failures."""

    out: list[SqlCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.sql:
            out.append(candidate)
            continue
        key = _normalize_sql_key(candidate.sql)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def group_sql_candidates(candidates: list[SqlCandidate]) -> list[SqlCandidateGroup]:
    """Group executable candidates by identical execution result signature."""

    groups_by_signature: dict[str, SqlCandidateGroup] = {}
    for candidate in candidates:
        if not candidate.sql or candidate.execute_error or not candidate.result_signature:
            continue
        group = groups_by_signature.get(candidate.result_signature)
        if group is None:
            group = SqlCandidateGroup(
                group_id=f"g{len(groups_by_signature) + 1}",
                candidates=[],
                result_signature=candidate.result_signature,
            )
            groups_by_signature[candidate.result_signature] = group
        candidate.group_id = group.group_id
        group.candidates.append(candidate)

    groups = list(groups_by_signature.values())
    for group in groups:
        for candidate in group.candidates:
            candidate.group_size = len(group.candidates)
    return groups


def fallback_select_sql_candidate(
    candidates: list[SqlCandidate],
    *,
    reason: str,
) -> SqlCandidate | None:
    """Stable fallback when tournament selection cannot produce a winner."""

    for candidate in candidates:
        candidate.selected = False
        candidate.selection_reason = None

    ranked = sorted(
        [candidate for candidate in candidates if candidate.sql],
        key=_fallback_rank_key,
        reverse=True,
    )
    if not ranked:
        return None
    selected = ranked[0]
    selected.selected = True
    selected.selection_reason = reason
    selected.score = max(selected.score, 1.0)
    return selected


def try_consensus_sql_candidate(groups: list[SqlCandidateGroup]) -> SqlCandidate | None:
    """Prefer the largest executable result group when it has a clear majority."""

    if not groups:
        return None
    ranked = sorted(groups, key=lambda group: len(group.candidates), reverse=True)
    top = ranked[0]
    if len(top.candidates) < 2:
        return None
    if len(ranked) == 1 or len(top.candidates) > len(ranked[1].candidates):
        return fallback_select_sql_candidate(
            top.candidates,
            reason=f"consensus execution result (n={len(top.candidates)})",
        )
    return None


def _fallback_rank_key(candidate: SqlCandidate) -> tuple[int, int, int, float]:
    executable = 1 if candidate.execute_error is None else 0
    grouped = 1 if candidate.group_id else 0
    fixed = 1 if candidate.fixed else 0
    return (executable, grouped, candidate.group_size, candidate.wins + fixed * 0.01)


def _normalize_sql_key(sql: str) -> str:
    return _SPACE_PATTERN.sub(" ", (sql or "").strip().lower())


__all__ = [
    "dedupe_sql_candidates",
    "fallback_select_sql_candidate",
    "group_sql_candidates",
    "try_consensus_sql_candidate",
]
