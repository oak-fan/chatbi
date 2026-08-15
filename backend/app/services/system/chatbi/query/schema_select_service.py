"""ChatBI schema linking and schema-vector retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from cogmait_shared.core.api_codes import ErrorCode, HttpStatus

from .....constants.chatbi.datasource import CHATBI_VECTOR_DIMENSIONS
from .....core.config import get_settings
from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from .....domain.system.llm import EmbeddingRequest
from .....repositories.system.chatbi import ChatbiDatasourceRepository
from ...llm_service import LLMService
from ...service_error import ServiceError
from ..common.schema_validator import subset_db_schema, validate_db_schema
from ..datasource.schema_vector_service import TABLE_VECTOR_COLUMN
from ..vector import ChatbiVectorStore, build_chatbi_vector_settings

_SCHEMA_LINKING_RERANK_MODEL = "qwen3-reranker-0.6b"
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass(slots=True)
class _SchemaCandidate:
    table_name: str
    column_name: str
    kind: str
    document: str
    vector_score: float = 0.0
    lexical_score: float = 0.0
    rerank_score: float | None = None
    score: float = 0.0

    @property
    def ref(self) -> str:
        if self.kind == "table":
            return self.table_name
        return f"{self.table_name}.{self.column_name}"


class ChatbiSchemaSelectServiceError(ServiceError):
    """ChatBI schema linking service error."""

    @classmethod
    def bad_request(cls, message: str) -> ChatbiSchemaSelectServiceError:
        return cls(
            message,
            status_code=HttpStatus.BAD_REQUEST,
            code=ErrorCode.PARAMS_INVALID,
        )

    @classmethod
    def not_found(cls, message: str = "记录不存在") -> ChatbiSchemaSelectServiceError:
        return cls(
            message,
            status_code=HttpStatus.NOT_FOUND,
            code=ErrorCode.NOT_FOUND,
        )

    @classmethod
    def system_error(cls, message: str) -> ChatbiSchemaSelectServiceError:
        return cls(
            message,
            status_code=HttpStatus.INTERNAL_ERROR,
            code=ErrorCode.SYSTEM_ERROR,
        )


class ChatbiSchemaSelectService:
    """Retrieve and rank relevant schema items for Text2SQL and value founding."""

    def __init__(
        self,
        *,
        session: Any,
        llm_service: LLMService | None = None,
        vector_store: ChatbiVectorStore | None = None,
        datasource_repo: ChatbiDatasourceRepository | None = None,
    ) -> None:
        self._session = session
        self._llm = llm_service or LLMService()
        self._vector_store = vector_store or ChatbiVectorStore(
            session=session,
            store_settings=build_chatbi_vector_settings(),
        )
        self._ds_repo = datasource_repo or ChatbiDatasourceRepository(session)

    async def select_schema_subset(
        self,
        *,
        user_id: int,
        datasource_id: int,
        question_text: str,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        linking = await self.link_schema(
            user_id=user_id,
            datasource_id=datasource_id,
            question_text=question_text,
            top_k=top_k,
            use_rerank=False,
        )
        return dict(linking["selected_schema"])

    async def link_schema(
        self,
        *,
        user_id: int,
        datasource_id: int,
        question_text: str,
        top_k: int | None = None,
        use_rerank: bool = False,
        db_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_schema = db_schema
        if record_schema is None:
            record = await self._ds_repo.get_for_user(datasource_id, user_id)
            if record is None or record.db_schema is None:
                raise ChatbiSchemaSelectServiceError.not_found("数据源不存在或未预处理")
            record_schema = record.db_schema
        full_schema = validate_db_schema(record_schema).to_json_dict()
        schema_record = ChatbiDbSchemaRecord.from_json_dict(full_schema)
        k = top_k or get_settings().vector_default_top_k
        candidates = await self._rank_schema_candidates(
            datasource_id=datasource_id,
            question_text=question_text,
            schema=schema_record,
            top_k=max(k, 1),
            use_rerank=use_rerank,
        )
        column_candidates = [c for c in candidates if c.kind == "column"]
        table_candidates = [c for c in candidates if c.kind == "table"]
        selected_refs = {
            (c.table_name, c.column_name)
            for c in column_candidates[:k]
            if c.column_name and c.column_name != TABLE_VECTOR_COLUMN
        }
        selected_schema = subset_db_schema(full_schema, selected_refs)
        return {
            "full_schema": full_schema,
            "selected_schema": selected_schema,
            "schema_fields": [f"{t}.{c}" for t, c in sorted(selected_refs)],
            "table_candidates": [_candidate_to_dict(c) for c in table_candidates[: min(k, 10)]],
            "column_candidates": [_candidate_to_dict(c) for c in column_candidates[:k]],
            "hints_text": format_schema_linking_hints(
                table_candidates=table_candidates[: min(k, 10)],
                column_candidates=column_candidates[:k],
            ),
        }

    async def candidate_columns_for_literals(
        self,
        *,
        datasource_id: int,
        question_text: str,
        literals: list[str],
        schema: ChatbiDbSchemaRecord,
        top_k: int = 12,
        min_score: float = 0.08,
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for literal in literals:
            local_text = _local_context_for_literal(question_text, literal) or literal
            candidates = await self._rank_schema_candidates(
                datasource_id=datasource_id,
                question_text=local_text,
                schema=schema,
                top_k=max(top_k, 1),
                use_rerank=False,
            )
            out[literal] = [
                _candidate_to_dict(c)
                for c in candidates
                if c.kind == "column" and c.score >= min_score
            ][:top_k]
        return out

    async def _rank_schema_candidates(
        self,
        *,
        datasource_id: int,
        question_text: str,
        schema: ChatbiDbSchemaRecord,
        top_k: int,
        use_rerank: bool,
    ) -> list[_SchemaCandidate]:
        vector_scores = await self._schema_vector_scores(
            datasource_id=datasource_id,
            question_text=question_text,
            top_k=max(top_k * 4, 60),
        )
        candidates = _schema_candidates_from_record(schema)
        question_tokens = _token_set(question_text)
        table_vector_scores: dict[str, float] = {}
        for ref, score in vector_scores.items():
            if ref.endswith(f".{TABLE_VECTOR_COLUMN}"):
                table_name = ref.rsplit(".", 1)[0]
                table_vector_scores[table_name] = max(score, table_vector_scores.get(table_name, 0.0))
        for candidate in candidates:
            if candidate.kind == "table":
                candidate.vector_score = vector_scores.get(
                    f"{candidate.table_name}.{TABLE_VECTOR_COLUMN}",
                    0.0,
                )
            else:
                candidate.vector_score = max(
                    vector_scores.get(candidate.ref, 0.0),
                    table_vector_scores.get(candidate.table_name, 0.0) * 0.65,
                )
            candidate.lexical_score = _lexical_score(question_tokens, candidate.document)
            candidate.score = (candidate.vector_score * 0.58) + (candidate.lexical_score * 0.42)
        candidates.sort(key=lambda item: (-item.score, item.kind, item.ref))
        if use_rerank:
            rerank_pool = candidates[: max(top_k * 3, 30)]
            await self._rerank_candidates(
                question_text=question_text,
                candidates=rerank_pool,
                top_n=max(top_k * 2, 20),
            )
            for candidate in rerank_pool:
                if candidate.rerank_score is not None:
                    candidate.score = (candidate.score * 0.45) + (
                        float(candidate.rerank_score) * 0.55
                    )
            candidates.sort(key=lambda item: (-item.score, item.kind, item.ref))
        return candidates

    async def _schema_vector_scores(
        self,
        *,
        datasource_id: int,
        question_text: str,
        top_k: int,
    ) -> dict[str, float]:
        emb = await self._llm.aembedding(EmbeddingRequest(input_texts=_schema_query_texts(question_text)))
        if not emb.embeddings:
            raise ChatbiSchemaSelectServiceError.system_error("问题向量化失败")
        scores: dict[str, float] = {}
        for embedding in emb.embeddings:
            if len(embedding) != CHATBI_VECTOR_DIMENSIONS:
                raise ChatbiSchemaSelectServiceError.bad_request(
                    f"向量维度不匹配，期望 {CHATBI_VECTOR_DIMENSIONS}，实际 {len(embedding)}"
                )
            hits = await self._vector_store.search_schema(
                datasource_id=datasource_id,
                embedding=embedding,
                top_k=top_k,
            )
            for hit in hits:
                ref = f"{hit.table_name}.{hit.column_name}"
                scores[ref] = max(scores.get(ref, 0.0), float(hit.score))
        return scores

    async def _rerank_candidates(
        self,
        *,
        question_text: str,
        candidates: list[_SchemaCandidate],
        top_n: int,
    ) -> None:
        if not candidates:
            return
        results = await _call_rerank_endpoint(
            query=question_text,
            documents=[c.document for c in candidates],
            top_n=min(top_n, len(candidates)),
        )
        if not results:
            return
        for item in results:
            idx = _coerce_int(item.get("index"))
            if idx < 0 or idx >= len(candidates):
                continue
            score = _coerce_float(
                item.get("relevance_score", item.get("score", item.get("relevanceScore")))
            )
            candidates[idx].rerank_score = score


def format_schema_linking_hints(
    *,
    table_candidates: list[_SchemaCandidate],
    column_candidates: list[_SchemaCandidate],
) -> str | None:
    if not table_candidates and not column_candidates:
        return None
    lines = [
        "# Schema linking hints",
        "The full schema is still available. Treat these as ranked relevance hints, not as the only usable schema.",
    ]
    if table_candidates:
        lines.extend(["", "Relevant tables:"])
        for item in table_candidates:
            lines.append(f"- {item.table_name} (score={item.score:.3f})")
    if column_candidates:
        lines.extend(["", "Relevant columns:"])
        for item in column_candidates:
            reasons = []
            if item.vector_score:
                reasons.append(f"vector={item.vector_score:.3f}")
            if item.lexical_score:
                reasons.append(f"lexical={item.lexical_score:.3f}")
            if item.rerank_score is not None:
                reasons.append(f"rerank={item.rerank_score:.3f}")
            suffix = f" ({', '.join(reasons)})" if reasons else ""
            lines.append(f"- {item.table_name}.{item.column_name}{suffix}")
    return "\n".join(lines)


def _schema_candidates_from_record(schema: ChatbiDbSchemaRecord) -> list[_SchemaCandidate]:
    candidates: list[_SchemaCandidate] = []
    for table in schema.tables:
        table_doc_parts = [
            "kind=table",
            f"table={table.table_name}",
            "columns=" + ", ".join(col.name for col in table.columns),
        ]
        table_samples: list[str] = []
        for col in table.columns:
            if col.description:
                table_doc_parts.append(f"{col.name}_description={col.description}")
            if col.comment:
                table_doc_parts.append(f"{col.name}_comment={col.comment}")
            if col.samples:
                table_samples.append(f"{col.name}=[{', '.join(col.samples[:3])}]")
        if table_samples:
            table_doc_parts.append("sample_values=" + "; ".join(table_samples[:12]))
        candidates.append(
            _SchemaCandidate(
                table_name=table.table_name,
                column_name=TABLE_VECTOR_COLUMN,
                kind="table",
                document=" | ".join(table_doc_parts),
            )
        )
        for col in table.columns:
            parts = [
                "kind=column",
                f"table={table.table_name}",
                f"column={col.name}",
                f"type={col.type}",
            ]
            if col.description:
                parts.append(f"description={col.description}")
            if col.comment:
                parts.append(f"comment={col.comment}")
            if col.constraints:
                parts.append(f"constraints={', '.join(col.constraints)}")
            if col.samples:
                parts.append(f"sample_values={', '.join(col.samples[:8])}")
            candidates.append(
                _SchemaCandidate(
                    table_name=table.table_name,
                    column_name=col.name,
                    kind="column",
                    document=" | ".join(parts),
                )
            )
    return candidates


def _candidate_to_dict(candidate: _SchemaCandidate) -> dict[str, Any]:
    data = {
        "table_name": candidate.table_name,
        "column_name": None if candidate.kind == "table" else candidate.column_name,
        "kind": candidate.kind,
        "score": candidate.score,
        "vector_score": candidate.vector_score,
        "lexical_score": candidate.lexical_score,
    }
    if candidate.rerank_score is not None:
        data["rerank_score"] = candidate.rerank_score
    return data


async def _call_rerank_endpoint(
    *,
    query: str,
    documents: list[str],
    top_n: int,
) -> list[dict[str, Any]]:
    settings = get_settings()
    base_url = (settings.litellm_api_base or "").rstrip("/")
    api_key = settings.litellm_api_key or ""
    if not base_url or not api_key or not documents:
        return []
    payload = {
        "model": _SCHEMA_LINKING_RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_n,
        "return_documents": False,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=settings.litellm_timeout) as client:
            response = await client.post(f"{base_url}/rerank", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return []
    results = data.get("results")
    if not isinstance(results, list):
        output = data.get("output")
        if isinstance(output, dict):
            results = output.get("results")
    if not isinstance(results, list):
        data_items = data.get("data")
        results = data_items if isinstance(data_items, list) else []
    return [item for item in results if isinstance(item, dict)]


def _schema_query_texts(question_text: str) -> list[str]:
    text = question_text.strip()
    queries = [text] if text else []
    for match in re.finditer(r"(?<!\w)(?:>=|<=|>|<|=)?\s*[-+]?\d+(?:\.\d+)?", text):
        context = _window_around_span(text, match.start(), match.end())
        if context and context not in queries:
            queries.append(context)
    for match in re.finditer(r"['\"]([^'\"]{2,120})['\"]", text):
        context = _window_around_span(text, match.start(), match.end())
        if context and context not in queries:
            queries.append(context)
    return queries[:6] or [question_text]


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _local_context_for_literal(question_text: str, literal: str) -> str:
    if not literal:
        return ""
    idx = question_text.casefold().find(literal.casefold())
    if idx < 0:
        return ""
    return _window_around_span(question_text, idx, idx + len(literal))


def _window_around_span(text: str, start: int, end: int, *, radius: int = 80) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return " ".join(text[left:right].split())


def _token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _WORD_RE.findall(_split_identifier(text).casefold()):
        if len(token) > 1:
            tokens.add(token)
    return tokens


def _split_identifier(text: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.sub(r"[_\-.]+", " ", text)


def _lexical_score(question_tokens: set[str], document: str) -> float:
    if not question_tokens:
        return 0.0
    doc_tokens = _token_set(document)
    if not doc_tokens:
        return 0.0
    overlap = question_tokens & doc_tokens
    if not overlap:
        return 0.0
    precision = len(overlap) / len(doc_tokens)
    recall = len(overlap) / len(question_tokens)
    return (2 * precision * recall) / (precision + recall)


__all__ = [
    "ChatbiSchemaSelectService",
    "ChatbiSchemaSelectServiceError",
    "format_schema_linking_hints",
]
