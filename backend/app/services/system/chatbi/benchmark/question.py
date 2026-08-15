"""Benchmark 问题组装。"""

from __future__ import annotations


def build_benchmark_question(
    question: str,
    evidence: str | None,
    *,
    evidence_enabled: bool,
) -> str:
    """组装基准评价实际送入 ChatBI 的问题文本。"""

    base = (question or "").rstrip()
    if not evidence_enabled:
        return base
    evidence_text = (evidence or "").strip()
    if not evidence_text:
        return base
    return f"{base}\n\n# Evidence\n{evidence_text}"
