"""ChatBI 向量 Milvus 实现。"""

from __future__ import annotations

from typing import Any, cast

from cogmait_shared.core.id_generator import generate_snowflake_id

from .....domain.system.chatbi.vector import (
    ChatbiBusinessKnowledgeSearchHit,
    ChatbiQsqlSearchHit,
    ChatbiSchemaSearchHit,
    ChatbiSchemaVectorRow,
)
from ...vector_store import VectorStoreError, VectorStoreSettings


class ChatbiMilvusVectorProvider:
    """独立于 knowledge_chunk 的 ChatBI Milvus collections。"""

    _SCHEMA_COLLECTION = "chatbi_schema_vector"
    _QSQL_COLLECTION = "chatbi_qsql_vector"
    _BIZKN_COLLECTION = "chatbi_business_knowledge_vector"

    def __init__(self, *, store_settings: VectorStoreSettings) -> None:
        self._settings = store_settings

    def initialize(self) -> None:
        client = self._get_client()
        for name in (
            self._schema_collection(),
            self._qsql_collection(),
            self._bizkn_collection(),
        ):
            client.create_collection_if_missing(collection_name=name)
            self._validate_collection_dimension(client=client, collection_name=name)

    async def rebuild_schema_vectors(
        self,
        *,
        datasource_id: int,
        rows: list[ChatbiSchemaVectorRow],
        user_id: int | None,
    ) -> None:
        del user_id
        client = self._get_client()
        collection = self._schema_collection()
        self._require_collection(client, collection)
        client.delete(
            collection_name=collection,
            filter=f"datasource_id == {datasource_id}",
            timeout=self._settings.timeout_seconds,
        )
        if not rows:
            return
        client.insert(
            collection_name=collection,
            data=[
                {
                    "id": generate_snowflake_id(),
                    "datasource_id": row.datasource_id,
                    "table_name": row.table_name,
                    "column_name": row.column_name,
                    "embedding": row.embedding,
                }
                for row in rows
            ],
            timeout=self._settings.timeout_seconds,
        )

    async def search_schema(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiSchemaSearchHit]:
        client = self._get_client()
        collection = self._schema_collection()
        self._require_collection(client, collection)
        rows = self._search(
            client=client,
            collection_name=collection,
            embedding=embedding,
            top_k=top_k,
            filter_expr=f"datasource_id == {datasource_id}",
            id_field="id",
        )
        hits: list[ChatbiSchemaSearchHit] = []
        for row in rows:
            entity = row.get("entity") or {}
            hits.append(
                ChatbiSchemaSearchHit(
                    table_name=str(entity.get("table_name", "")),
                    column_name=str(entity.get("column_name", "")),
                    score=float(row.get("distance") or 0.0),
                )
            )
        return hits

    async def upsert_qsql_vector(
        self,
        *,
        qsql_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None:
        del user_id
        await self.soft_delete_qsql_vector(qsql_id=qsql_id, user_id=None)
        client = self._get_client()
        collection = self._qsql_collection()
        self._require_collection(client, collection)
        client.insert(
            collection_name=collection,
            data=[
                {
                    "id": qsql_id,
                    "qsql_id": qsql_id,
                    "datasource_id": datasource_id,
                    "embedding": embedding,
                }
            ],
            timeout=self._settings.timeout_seconds,
        )

    async def soft_delete_qsql_vector(self, *, qsql_id: int, user_id: int | None) -> None:
        del user_id
        client = self._get_client()
        collection = self._qsql_collection()
        self._require_collection(client, collection)
        client.delete(
            collection_name=collection,
            ids=[qsql_id],
            timeout=self._settings.timeout_seconds,
        )

    async def soft_delete_qsql_vectors_by_datasource(
        self,
        *,
        datasource_id: int,
        user_id: int | None,
    ) -> None:
        del user_id
        client = self._get_client()
        collection = self._qsql_collection()
        self._require_collection(client, collection)
        client.delete(
            collection_name=collection,
            filter=f"datasource_id == {datasource_id}",
            timeout=self._settings.timeout_seconds,
        )

    async def soft_delete_business_knowledge_vectors_by_ids(
        self,
        *,
        record_ids: list[int],
        user_id: int | None,
    ) -> None:
        del user_id
        if not record_ids:
            return
        client = self._get_client()
        collection = self._bizkn_collection()
        self._require_collection(client, collection)
        client.delete(
            collection_name=collection,
            ids=record_ids,
            timeout=self._settings.timeout_seconds,
        )

    async def search_qsql(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiQsqlSearchHit]:
        client = self._get_client()
        collection = self._qsql_collection()
        self._require_collection(client, collection)
        rows = self._search(
            client=client,
            collection_name=collection,
            embedding=embedding,
            top_k=top_k,
            filter_expr=f"datasource_id == {datasource_id}",
            id_field="qsql_id",
        )
        return [
            ChatbiQsqlSearchHit(
                qsql_id=int(row["id"]),
                score=float(row.get("distance") or 0.0),
            )
            for row in rows
        ]

    async def search_qsql_pool(
        self,
        *,
        datasource_ids: list[int],
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiQsqlSearchHit]:
        ids = sorted({int(item) for item in datasource_ids})
        if not ids:
            return []
        client = self._get_client()
        collection = self._qsql_collection()
        self._require_collection(client, collection)
        if len(ids) == 1:
            filter_expr = f"datasource_id == {ids[0]}"
        else:
            filter_expr = f"datasource_id in [{', '.join(str(item) for item in ids)}]"
        rows = self._search(
            client=client,
            collection_name=collection,
            embedding=embedding,
            top_k=top_k,
            filter_expr=filter_expr,
            id_field="qsql_id",
        )
        return [
            ChatbiQsqlSearchHit(
                qsql_id=int(row["id"]),
                score=float(row.get("distance") or 0.0),
            )
            for row in rows
        ]

    async def upsert_business_knowledge_vector(
        self,
        *,
        business_knowledge_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None:
        del user_id
        await self.soft_delete_business_knowledge_vector(
            business_knowledge_id=business_knowledge_id,
            user_id=None,
        )
        client = self._get_client()
        collection = self._bizkn_collection()
        self._require_collection(client, collection)
        client.insert(
            collection_name=collection,
            data=[
                {
                    "id": business_knowledge_id,
                    "business_knowledge_id": business_knowledge_id,
                    "datasource_id": datasource_id,
                    "embedding": embedding,
                }
            ],
            timeout=self._settings.timeout_seconds,
        )

    async def soft_delete_business_knowledge_vector(
        self,
        *,
        business_knowledge_id: int,
        user_id: int | None,
    ) -> None:
        del user_id
        client = self._get_client()
        collection = self._bizkn_collection()
        self._require_collection(client, collection)
        client.delete(
            collection_name=collection,
            ids=[business_knowledge_id],
            timeout=self._settings.timeout_seconds,
        )

    async def search_business_knowledge(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiBusinessKnowledgeSearchHit]:
        client = self._get_client()
        collection = self._bizkn_collection()
        self._require_collection(client, collection)
        rows = self._search(
            client=client,
            collection_name=collection,
            embedding=embedding,
            top_k=top_k,
            filter_expr=f"datasource_id == {datasource_id}",
            id_field="business_knowledge_id",
        )
        return [
            ChatbiBusinessKnowledgeSearchHit(
                business_knowledge_id=int(row["id"]),
                score=float(row.get("distance") or 0.0),
            )
            for row in rows
        ]

    def _search(
        self,
        *,
        client: Any,
        collection_name: str,
        embedding: list[float],
        top_k: int,
        filter_expr: str | None,
        id_field: str,
    ) -> list[dict[str, Any]]:
        del id_field
        kwargs: dict[str, Any] = {
            "collection_name": collection_name,
            "data": [embedding],
            "limit": top_k,
            "output_fields": ["*"],
            "search_params": {"metric_type": "COSINE", "params": {}},
            "timeout": self._settings.timeout_seconds,
        }
        if filter_expr:
            kwargs["filter"] = filter_expr
        search_result = client.search(**kwargs)
        rows = (
            search_result[0]
            if search_result and isinstance(search_result[0], list)
            else search_result
        )
        return list(rows or [])

    def _get_client(self) -> Any:
        try:
            from pymilvus import DataType, MilvusClient
        except ImportError as exc:
            raise VectorStoreError("当前环境缺少 pymilvus，无法使用 Milvus 后端") from exc
        if self._settings.milvus_uri is None:
            raise VectorStoreError("Milvus 连接配置不完整")
        return _MilvusAdapter(
            client=MilvusClient(
                uri=cast(str, self._settings.milvus_uri),
                token=self._settings.milvus_token or "",
                db_name=self._settings.milvus_database,
                timeout=self._settings.timeout_seconds,
            ),
            data_type=DataType,
            dimensions=self._settings.dimensions,
        )

    def _schema_collection(self) -> str:
        return f"{self._settings.milvus_collection_prefix}_{self._SCHEMA_COLLECTION}"

    def _qsql_collection(self) -> str:
        return f"{self._settings.milvus_collection_prefix}_{self._QSQL_COLLECTION}"

    def _bizkn_collection(self) -> str:
        return f"{self._settings.milvus_collection_prefix}_{self._BIZKN_COLLECTION}"

    def _validate_collection_dimension(self, *, client: Any, collection_name: str) -> None:
        actual = client.get_collection_dimension(collection_name=collection_name)
        if actual is not None and actual != self._settings.dimensions:
            raise VectorStoreError(
                f"Milvus collection 向量维度不匹配，期望 {self._settings.dimensions}，实际 {actual}"
            )

    def _require_collection(self, client: Any, collection_name: str) -> None:
        if not client.has_collection(collection_name=collection_name):
            raise VectorStoreError(f"Milvus collection {collection_name} 未初始化")


class _MilvusAdapter:
    def __init__(self, *, client: Any, data_type: Any, dimensions: int) -> None:
        self._client = client
        self._data_type = data_type
        self._dimensions = dimensions

    def create_collection_if_missing(self, *, collection_name: str) -> None:
        if self._client.has_collection(collection_name=collection_name):
            return
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=True)
        if "chatbi_schema" in collection_name:
            schema.add_field("id", datatype=self._data_type.INT64, is_primary=True)
            schema.add_field("datasource_id", datatype=self._data_type.INT64)
            schema.add_field("table_name", datatype=self._data_type.VARCHAR, max_length=512)
            schema.add_field("column_name", datatype=self._data_type.VARCHAR, max_length=512)
        elif "chatbi_qsql" in collection_name:
            schema.add_field("id", datatype=self._data_type.INT64, is_primary=True)
            schema.add_field("qsql_id", datatype=self._data_type.INT64)
            schema.add_field("datasource_id", datatype=self._data_type.INT64)
        else:
            schema.add_field("id", datatype=self._data_type.INT64, is_primary=True)
            schema.add_field("business_knowledge_id", datatype=self._data_type.INT64)
            schema.add_field("datasource_id", datatype=self._data_type.INT64)
        schema.add_field(
            "embedding",
            datatype=self._data_type.FLOAT_VECTOR,
            dim=self._dimensions,
        )
        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
            params={},
        )
        self._client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )

    def get_collection_dimension(self, *, collection_name: str) -> int | None:
        if not hasattr(self._client, "describe_collection"):
            return None
        description = self._client.describe_collection(collection_name=collection_name)
        if not isinstance(description, dict):
            return None
        for field in description.get("fields") or []:
            if not isinstance(field, dict):
                continue
            if (field.get("name") or field.get("field_name")) != "embedding":
                continue
            for key in ("dim",):
                if field.get(key) is not None:
                    return int(field[key])
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


__all__ = ["ChatbiMilvusVectorProvider"]
