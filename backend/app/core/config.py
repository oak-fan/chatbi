"""cogmait-chatbi 配置模块。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..observability.provider_name import ObservabilityProviderName

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs" / "cogmait_chatbi"


class Settings(BaseSettings):
    """ChatBI 独立服务配置。"""

    environment: str = Field(default="local", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")
    log_dir: Path = Field(default=DEFAULT_LOG_DIR, alias="LOG_DIR")
    log_path_template: str | None = Field(default=None, alias="CHATBI_LOG_PATH_TEMPLATE")
    database_url: str = Field(
        default="postgresql+asyncpg://cogmait:cogmait@localhost:5432/cogmait",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_key_prefix: str = Field(default="", alias="REDIS_KEY_PREFIX")
    default_user_id: int = Field(default=1, alias="DEFAULT_USER_ID")
    default_username: str = Field(default="chatbi", alias="DEFAULT_USERNAME")

    litellm_api_base: str | None = Field(default=None, alias="LITELLM_API_BASE")
    litellm_api_key: str | None = Field(default=None, alias="LITELLM_API_KEY")
    litellm_timeout: float = Field(default=60.0, alias="LITELLM_TIMEOUT")
    litellm_num_retries: int = Field(default=2, alias="LITELLM_NUM_RETRIES")
    default_completion_model: str | None = Field(default=None, alias="DEFAULT_COMPLETION_MODEL")
    default_embedding_model: str | None = Field(default=None, alias="DEFAULT_EMBEDDING_MODEL")
    default_rerank_model: str | None = Field(default=None, alias="DEFAULT_RERANK_MODEL")

    observability_enabled: bool = Field(default=True, alias="OBSERVABILITY_ENABLED")
    observability_provider: ObservabilityProviderName = Field(
        default=ObservabilityProviderName.NOOP,
        alias="OBSERVABILITY_PROVIDER",
    )
    observability_env: str = Field(default="local", alias="OBSERVABILITY_ENV")
    observability_service_name: str = Field(
        default="cogmait-chatbi",
        alias="OBSERVABILITY_SERVICE_NAME",
    )
    observability_capture_prompt: bool = Field(
        default=False,
        alias="OBSERVABILITY_CAPTURE_PROMPT",
    )
    observability_capture_response: bool = Field(
        default=False,
        alias="OBSERVABILITY_CAPTURE_RESPONSE",
    )
    observability_litellm_message_logging_enabled: bool = Field(
        default=False,
        alias="OBSERVABILITY_LITELLM_MESSAGE_LOGGING_ENABLED",
    )
    observability_capture_tool_args: bool = Field(
        default=False,
        alias="OBSERVABILITY_CAPTURE_TOOL_ARGS",
    )
    observability_mask_user_id: bool = Field(
        default=True,
        alias="OBSERVABILITY_MASK_USER_ID",
    )
    langfuse_base_url: str | None = Field(default=None, alias="LANGFUSE_BASE_URL")
    langfuse_host: str | None = Field(default=None, alias="LANGFUSE_HOST")
    langfuse_public_key: str | None = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(default=None, alias="LANGFUSE_SECRET_KEY")

    vector_backend: str = Field(default="postgres", alias="VECTOR_BACKEND")
    vector_dimensions: int = Field(default=1024, alias="VECTOR_DIMENSIONS")
    vector_default_top_k: int = Field(default=10, alias="VECTOR_DEFAULT_TOP_K")
    vector_timeout: float = Field(default=30.0, alias="VECTOR_TIMEOUT")
    vector_postgres_ivfflat_lists: int = Field(
        default=100,
        alias="VECTOR_POSTGRES_IVFFLAT_LISTS",
    )
    milvus_uri: str | None = Field(default=None, alias="MILVUS_URI")
    milvus_token: str | None = Field(default=None, alias="MILVUS_TOKEN")
    milvus_database: str = Field(default="default", alias="MILVUS_DATABASE")
    milvus_collection_prefix: str = Field(
        default="cogmait",
        alias="MILVUS_COLLECTION_PREFIX",
    )

    snowflake_datacenter_id: int = Field(default=0, alias="SNOWFLAKE_DATACENTER_ID")
    snowflake_worker_id: int = Field(default=0, alias="SNOWFLAKE_WORKER_ID")

    chatbi_datasource_credential_encryption_key: str | None = Field(
        default=None,
        alias="CHATBI_DATASOURCE_CREDENTIAL_ENCRYPTION_KEY",
    )
    chatbi_file_upload_database_url: str | None = Field(
        default=None,
        alias="CHATBI_FILE_UPLOAD_DATABASE_URL",
    )
    chatbi_benchmark_root: Path | None = Field(
        default=None,
        alias="CHATBI_BENCHMARK_ROOT",
    )
    chatbi_bird_minidev_root: Path | None = Field(
        default=None,
        alias="CHATBI_BIRD_MINIDEV_ROOT",
    )
    chatbi_multi_agent_knowledge_database_url: str | None = Field(
        default="postgresql+asyncpg://postgres:123456@47.94.248.19:18004/postgres",
        alias="CHATBI_MULTI_AGENT_KNOWLEDGE_DATABASE_URL",
    )
    chatbi_knowledge_database_url: str | None = Field(
        default=None,
        alias="CHATBI_KNOWLEDGE_DATABASE_URL",
    )
    chatbi_benchmark_import_user_id: int | None = Field(
        default=None,
        alias="CHATBI_BENCHMARK_IMPORT_USER_ID",
    )

    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8001, alias="PORT")

    @field_validator(
        "litellm_api_base",
        "litellm_api_key",
        "vector_backend",
        "milvus_uri",
        "milvus_token",
        "milvus_database",
        "milvus_collection_prefix",
        "log_path_template",
        "observability_provider",
        "observability_env",
        "observability_service_name",
        "langfuse_base_url",
        "langfuse_host",
        "langfuse_public_key",
        "langfuse_secret_key",
        "default_completion_model",
        "default_embedding_model",
        "default_rerank_model",
        "chatbi_datasource_credential_encryption_key",
        "chatbi_file_upload_database_url",
        "chatbi_benchmark_root",
        "chatbi_bird_minidev_root",
        mode="before",
    )
    @classmethod
    def _normalize_optional_string(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("litellm_timeout", "vector_timeout")
    @classmethod
    def _validate_timeout(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("timeout 必须大于 0")
        return value

    @field_validator("litellm_num_retries")
    @classmethod
    def _validate_num_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("LITELLM_NUM_RETRIES 不能小于 0")
        return value

    @field_validator("observability_provider", mode="before")
    @classmethod
    def _validate_observability_provider(
        cls,
        value: ObservabilityProviderName | str | None,
    ) -> ObservabilityProviderName:
        if isinstance(value, ObservabilityProviderName):
            return value
        normalized = (value or "").strip().lower()
        try:
            return ObservabilityProviderName(normalized)
        except ValueError as exc:
            raise ValueError("OBSERVABILITY_PROVIDER 仅支持 noop 或 langfuse") from exc

    @field_validator(
        "vector_dimensions",
        "vector_default_top_k",
        "vector_postgres_ivfflat_lists",
        "default_user_id",
        "port",
    )
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("该配置项必须大于 0")
        return value

    @field_validator("snowflake_datacenter_id", "snowflake_worker_id")
    @classmethod
    def _validate_snowflake_id(cls, value: int) -> int:
        if value < 0:
            raise ValueError("snowflake id 不能小于 0")
        return value

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
