"""ChatBI 数据源领域对象。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE, CHATBI_PAGE_MAX_SIZE

MAX_PG_IDENT_LEN = 63
_PG_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_HOST_FORBIDDEN_RE = re.compile(r"[\s/@?#\\:]")
_IMPORT_COL_SUB_RE = re.compile(r"[\s()\-%.]+")


def _normalize_import_quoted_ident(name: str) -> str:
    """表格导入列名/表名：空格、()、-、%、. 替换为下划线，保留中文等其它字符。"""
    text = _IMPORT_COL_SUB_RE.sub("_", name)
    return re.sub(r"_+", "_", text).strip("_")


def _normalize_import_column_name(name: str) -> str:
    return _normalize_import_quoted_ident(name)


def _pg_ident_too_long(name: str) -> bool:
    return len(name.encode("utf-8")) > MAX_PG_IDENT_LEN


def _truncate_pg_ident_bytes(name: str, max_bytes: int = MAX_PG_IDENT_LEN) -> str:
    if len(name.encode("utf-8")) <= max_bytes:
        return name
    chars: list[str] = []
    total = 0
    for char in name:
        char_len = len(char.encode("utf-8"))
        if total + char_len > max_bytes:
            break
        chars.append(char)
        total += char_len
    return "".join(chars).rstrip("_") or "column"


def build_import_column_names(header: list[str]) -> list[str]:
    """表格首行表头 → PG 双引号列名列表（规范化、空列回退、重名加后缀）。"""
    cols: list[str] = []
    seen: set[str] = set()
    for idx, cell in enumerate(header):
        stripped = cell.strip()
        if stripped:
            base = _normalize_import_column_name(stripped)
            if not base:
                base = f"column_{idx + 1}"
        else:
            base = f"column_{idx + 1}"
        name = _allocate_import_column_name(base, seen)
        seen.add(name)
        cols.append(name)
    return cols


def _allocate_import_column_name(base: str, seen: set[str]) -> str:
    name = _truncate_pg_ident_bytes(base)
    if name not in seen:
        return name
    for n in range(2, len(seen) + 2):
        suffix = f"_{n}"
        prefix = (
            _truncate_pg_ident_bytes(
                base,
                MAX_PG_IDENT_LEN - len(suffix.encode("utf-8")),
            ).rstrip("_")
            or "column"
        )
        name = f"{prefix}{suffix}"
        if name not in seen:
            return name
    msg = "无法分配唯一列名"
    raise ValueError(msg)


def validate_pg_ident(name: str, *, field: str = "标识符") -> str:
    """校验并返回可用于 SQL 拼接的 PG 标识符（字母数字下划线）。"""
    cleaned = name.strip()
    if not cleaned:
        msg = f"{field} 不能为空"
        raise ValueError(msg)
    if field in ("列名", "表名"):
        normalized = _normalize_import_quoted_ident(cleaned)
        if not normalized:
            msg = f"{field} 不能为空"
            raise ValueError(msg)
        if _pg_ident_too_long(normalized):
            msg = f"{field} 超过 {MAX_PG_IDENT_LEN} 字节"
            raise ValueError(msg)
        return normalized
    if not _PG_IDENT_RE.match(cleaned):
        msg = f"{field} 含非法字符"
        raise ValueError(msg)
    if _pg_ident_too_long(cleaned):
        msg = f"{field} 超过 {MAX_PG_IDENT_LEN} 字节"
        raise ValueError(msg)
    return cleaned


def normalize_pg_schema_name(name: str | None, *, field: str = "schema_name") -> str | None:
    """规范化外部数据源 schema；空串视为未指定（落库默认 public）。"""
    if name is None:
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    return validate_pg_ident(cleaned, field=field)


def validate_datasource_host(host: str) -> str:
    """校验数据库 host，只接受纯主机名/IP，不接受 URL、端口、路径或用户信息。"""
    cleaned = _strip_required(host, field_name="host")
    if "://" in cleaned or _HOST_FORBIDDEN_RE.search(cleaned):
        msg = "host 不能包含协议、端口、路径或用户信息"
        raise ValueError(msg)
    if len(cleaned) > 253:
        msg = "host 过长"
        raise ValueError(msg)
    return cleaned


def _validate_datasource_port(port: int) -> int:
    if port < 1 or port > 65535:
        msg = "port 非法"
        raise ValueError(msg)
    return port


def _validate_positive_id(value: int, *, field_name: str) -> int:
    if value <= 0:
        msg = f"{field_name} 非法"
        raise ValueError(msg)
    return value


def _validate_positive_ids(values: list[int], *, field_name: str) -> list[int]:
    if not values:
        msg = f"{field_name} 不能为空"
        raise ValueError(msg)
    return [_validate_positive_id(int(value), field_name=field_name) for value in values]


class DataSourceOrigin(StrEnum):
    """数据源来源（直连外部库 / 表格文件上传）。"""

    EXTERNAL = "EXTERNAL"
    FILE_UPLOAD = "FILE_UPLOAD"


class DataSourceType(StrEnum):
    """支持的外部数据库类型。"""

    POSTGRESQL = "POSTGRESQL"
    MYSQL = "MYSQL"
    SQLITE = "SQLITE"


_SQLITE_PLACEHOLDER_CREDENTIAL = "sqlite"
_DATASOURCE_UPDATE_FIELDS = frozenset(
    {
        "name",
        "host",
        "port",
        "database",
        "schema_name",
        "username",
        "password",
        "extra_params",
        "remark",
    }
)
_DATASOURCE_UPDATE_REQUIRED_FIELDS = frozenset(
    {"name", "host", "port", "database", "username", "password"}
)


def _strip_required(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} 不能为空"
        raise ValueError(msg)
    return text


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_sqlite_db_file(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        msg = "extra_params.db_file 不能为空"
        raise ValueError(msg)
    if text.startswith("/") or ":" in text:
        msg = "extra_params.db_file 必须为挂载目录内相对路径"
        raise ValueError(msg)
    parts = [part for part in text.split("/") if part]
    if any(part == ".." for part in parts):
        msg = "extra_params.db_file 不能包含上级目录"
        raise ValueError(msg)
    if not parts or not parts[-1].lower().endswith(".sqlite"):
        msg = "extra_params.db_file 必须指向 .sqlite 文件"
        raise ValueError(msg)
    return "/".join(parts)


def normalize_sqlite_extra_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """规范化 SQLite 数据源连接参数。"""

    data = dict(params or {})
    data["db_file"] = _normalize_sqlite_db_file(data.get("db_file") or data.get("dbFile"))
    data.pop("dbFile", None)
    return data


@dataclass(slots=True)
class ChatbiDatasourceCreateInput:
    """创建外部库数据源。"""

    user_id: int
    name: str
    connector_type: str
    host: str | None
    port: int | None
    database: str | None
    schema_name: str | None
    username: str | None
    password: str | None
    extra_params: dict[str, Any] | None
    remark: str | None

    def __post_init__(self) -> None:
        self.name = _strip_required(self.name, field_name="name")
        self.connector_type = _strip_required(
            self.connector_type,
            field_name="connector_type",
        )
        if self.extra_params is None:
            self.extra_params = {}
        if self.connector_type == DataSourceType.SQLITE.value:
            self._normalize_sqlite_fields()
        else:
            self._normalize_network_database_fields()
        self.remark = _strip_optional(self.remark)

    def _normalize_network_database_fields(self) -> None:
        self.host = validate_datasource_host(_strip_required(self.host or "", field_name="host"))
        if self.port is None:
            msg = "port 不能为空"
            raise ValueError(msg)
        self.port = _validate_datasource_port(self.port)
        self.database = _strip_required(self.database or "", field_name="database")
        self.schema_name = normalize_pg_schema_name(_strip_optional(self.schema_name))
        self.username = _strip_required(self.username or "", field_name="username")
        self.password = _strip_required(self.password or "", field_name="password")

    def _normalize_sqlite_fields(self) -> None:
        self.extra_params = normalize_sqlite_extra_params(self.extra_params)
        db_file = str(self.extra_params["db_file"])
        self.host = "sqlite"
        self.port = 1
        self.database = _strip_optional(self.database) or db_file.rsplit("/", 1)[-1]
        self.schema_name = None
        self.username = _SQLITE_PLACEHOLDER_CREDENTIAL  # nosec B105
        self.password = _SQLITE_PLACEHOLDER_CREDENTIAL  # nosec B105


@dataclass(slots=True)
class ChatbiDatasourceFromFilesInput:
    """表格上传建源。"""

    user_id: int
    name: str
    file_ids: list[int]
    remark: str | None

    def __post_init__(self) -> None:
        self.name = _strip_required(self.name, field_name="name")
        self.remark = _strip_optional(self.remark)
        self.file_ids = _validate_positive_ids(self.file_ids, field_name="file_ids")


@dataclass(slots=True)
class ChatbiDatasourceFileUploadCreateInput:
    """创建表格上传数据源的连接配置。"""

    user_id: int
    name: str
    remark: str | None
    file_ids: list[int]
    host: str
    port: int
    database: str
    schema_name: str
    username: str
    encrypted_password: str
    extra_params: dict[str, object] | None = None

    def __post_init__(self) -> None:
        self.name = _strip_required(self.name, field_name="name")
        self.remark = _strip_optional(self.remark)
        self.file_ids = _validate_positive_ids(self.file_ids, field_name="file_ids")
        self.host = validate_datasource_host(self.host)
        self.port = _validate_datasource_port(self.port)
        self.database = _strip_required(self.database, field_name="database")
        schema_name = normalize_pg_schema_name(
            _strip_required(self.schema_name, field_name="schema_name")
        )
        if schema_name is None:
            msg = "schema_name 不能为空"
            raise ValueError(msg)
        self.schema_name = schema_name
        self.username = _strip_required(self.username, field_name="username")
        self.encrypted_password = _strip_required(
            self.encrypted_password,
            field_name="encrypted_password",
        )
        if self.extra_params is None:
            self.extra_params = {}


@dataclass(slots=True)
class ChatbiDatasourceUpdateInput:
    """更新数据源连接或展示字段的入参。"""

    user_id: int
    name: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    schema_name: str | None = None
    username: str | None = None
    password: str | None = None
    extra_params: dict[str, Any] | None = None
    remark: str | None = None
    provided_fields: frozenset[str] | set[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self.provided_fields = frozenset(str(item) for item in self.provided_fields)
        if not self.provided_fields:
            self.provided_fields = frozenset(
                field_name
                for field_name in _DATASOURCE_UPDATE_FIELDS
                if getattr(self, field_name) is not None
            )
        if not self.provided_fields:
            msg = "至少提供一个更新字段"
            raise ValueError(msg)
        unknown_fields = self.provided_fields - _DATASOURCE_UPDATE_FIELDS
        if unknown_fields:
            msg = "更新字段非法"
            raise ValueError(msg)
        for field_name in self.provided_fields & _DATASOURCE_UPDATE_REQUIRED_FIELDS:
            if getattr(self, field_name) is None:
                msg = f"{field_name} 不能为 null"
                raise ValueError(msg)
        if self.name is not None:
            self.name = _strip_required(self.name, field_name="name")
        if self.host is not None:
            self.host = validate_datasource_host(self.host)
        if self.port is not None:
            self.port = _validate_datasource_port(self.port)
        if self.database is not None:
            self.database = _strip_required(self.database, field_name="database")
        if self.schema_name is not None:
            self.schema_name = normalize_pg_schema_name(_strip_optional(self.schema_name))
        if self.username is not None:
            self.username = _strip_required(self.username, field_name="username")
        if self.password is not None:
            self.password = _strip_required(self.password, field_name="password")
        if self.remark is not None:
            self.remark = _strip_optional(self.remark)


@dataclass(slots=True)
class ChatbiDatasourceListParams:
    """数据源列表分页与筛选条件。"""

    user_id: int
    page: int = 1
    size: int = CHATBI_PAGE_DEFAULT_SIZE
    name_keyword: str | None = None
    connector_type_filter: str | None = None

    def __post_init__(self) -> None:
        if self.page < 1:
            msg = "page 非法"
            raise ValueError(msg)
        if self.size < 1 or self.size > CHATBI_PAGE_MAX_SIZE:
            msg = "size 非法"
            raise ValueError(msg)
        self.name_keyword = _strip_optional(self.name_keyword)
        self.connector_type_filter = _strip_optional(self.connector_type_filter)


@dataclass(slots=True)
class ChatbiDatasourceDeleteInput:
    """软删除数据源的入参。"""

    user_id: int
    datasource_id: int

    def __post_init__(self) -> None:
        self.datasource_id = _validate_positive_id(
            self.datasource_id,
            field_name="datasource_id",
        )


@dataclass(slots=True)
class ChatbiDatasourceExecuteSqlInput:
    """只读执行 SQL 的入参。"""

    user_id: int
    datasource_id: int
    sql: str

    def __post_init__(self) -> None:
        self.datasource_id = _validate_positive_id(
            self.datasource_id,
            field_name="datasource_id",
        )
        self.sql = _strip_required(self.sql, field_name="sql")


@dataclass(slots=True)
class ChatbiDatasourcePreprocessInput:
    """触发结构预处理任务入队的入参。"""

    user_id: int
    datasource_id: int

    def __post_init__(self) -> None:
        self.datasource_id = _validate_positive_id(
            self.datasource_id,
            field_name="datasource_id",
        )


@dataclass(slots=True)
class ChatbiDatasourcePreprocessRecord:
    """预处理任务入队结果。"""

    task_id: int


@dataclass(slots=True)
class ChatbiDatasourceRecord:
    """数据源详情（不含凭证密文）。"""

    id: int
    origin: str
    name: str
    connector_type: str
    host: str
    port: int
    database: str
    schema_name: str | None
    username: str
    import_file_ids: list[int]
    db_schema: dict[str, Any] | None
    db_schema_updated_at: datetime | None
    extra_params: dict[str, Any] | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ChatbiDatasourceConnectionRecord:
    """连接器解密所需字段（仅仓储/连接服务内部传递）。"""

    id: int
    connector_type: str
    host: str
    port: int
    database: str
    schema_name: str | None
    username: str
    encrypted_password: str
    extra_params: dict[str, Any] | None


__all__ = [
    "MAX_PG_IDENT_LEN",
    "build_import_column_names",
    "ChatbiDatasourceCreateInput",
    "ChatbiDatasourceDeleteInput",
    "ChatbiDatasourceExecuteSqlInput",
    "ChatbiDatasourceFileUploadCreateInput",
    "ChatbiDatasourceFromFilesInput",
    "ChatbiDatasourceListParams",
    "ChatbiDatasourceConnectionRecord",
    "ChatbiDatasourcePreprocessInput",
    "ChatbiDatasourcePreprocessRecord",
    "ChatbiDatasourceRecord",
    "ChatbiDatasourceUpdateInput",
    "DataSourceOrigin",
    "DataSourceType",
    "normalize_sqlite_extra_params",
    "normalize_pg_schema_name",
    "validate_datasource_host",
    "validate_pg_ident",
]
