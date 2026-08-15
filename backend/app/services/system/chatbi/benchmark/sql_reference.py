"""基于 SQLGlot 的 benchmark SQL 结构抽取（消解 alias → 物理 table.column）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify

_SQL_COMMENT_PATTERN = re.compile(r"(--[^\n\r]*|/\*.*?\*/)", flags=re.DOTALL)
_TABLE_PATTERN = re.compile(r"\b(?:from|join)\s+([`\"\[]?[A-Za-z_][\w.]*[`\"\]]?)", re.I)
_JOIN_PATTERN = re.compile(
    r"\bjoin\s+[`\"\[]?[A-Za-z_][\w.]*[`\"\]]?\s+(?:as\s+)?"
    r"(?:[A-Za-z_]\w*\s+)?on\s+(.+?)(?=\bjoin\b|\bwhere\b|\bgroup\b|\border\b|$)",
    re.I | re.S,
)
_COLUMN_PATTERN = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b")
_PREDICATE_PATTERN = re.compile(
    r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*(=|<>|!=|>|>=|<|<=|like|in)\s*"
    r"('([^']|'')*'|\"([^\"]|\"\")*\"|\d+(?:\.\d+)?)",
    re.I,
)
_CONNECTOR_DIALECT = {
    "SQLITE": "sqlite",
    "MYSQL": "mysql",
    "POSTGRESQL": "postgres",
    "ORACLE": "oracle",
    "SQLSERVER": "tsql",
}


@dataclass(frozen=True, slots=True)
class SqlReference:
    """从 SQL 解析出的结构参考集合。"""

    tables: tuple[str, ...]
    columns: tuple[str, ...]
    join_keys: tuple[str, ...]
    constant_predicates: tuple[str, ...]
    parse_status: str = "SUCCESS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tables": list(self.tables),
            "columns": list(self.columns),
            "join_keys": list(self.join_keys),
            "constant_predicates": list(self.constant_predicates),
            "parse_status": self.parse_status,
        }


def connector_type_to_dialect(connector_type: str | None) -> str:
    if not connector_type:
        return "sqlite"
    return _CONNECTOR_DIALECT.get(connector_type.strip().upper(), "sqlite")


def schema_map_from_db_schema(db_schema: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    if not isinstance(db_schema, dict):
        return {}
    tables = db_schema.get("tables")
    if not isinstance(tables, list):
        return {}
    schema: dict[str, dict[str, str]] = {}
    for item in tables:
        if not isinstance(item, dict):
            continue
        table_name = _normalize_ident(str(item.get("table_name") or ""))
        if not table_name:
            continue
        columns = item.get("columns") or []
        if not isinstance(columns, list):
            continue
        schema[table_name] = {
            _normalize_ident(str(col.get("name") or "")): str(col.get("type") or "TEXT")
            for col in columns
            if isinstance(col, dict) and col.get("name")
        }
    return schema


def extract_sql_reference(
    sql: str,
    *,
    db_schema: dict[str, Any] | None = None,
    dialect: str = "sqlite",
) -> SqlReference:
    """解析 SQL 并抽取 tables / columns / join keys / 常量谓词。"""

    text = (sql or "").strip()
    if not text:
        return SqlReference((), (), (), (), parse_status="EMPTY")

    schema_map = schema_map_from_db_schema(db_schema)
    try:
        expression = sqlglot.parse_one(text, read=dialect)
    except Exception:
        return _extract_with_regex_fallback(text)

    cte_names = _collect_cte_names(expression)
    alias_map = _collect_alias_map(expression, cte_names)

    if schema_map:
        try:
            expression = qualify(
                expression,
                schema=schema_map,
                dialect=dialect,
                validate_qualify_columns=False,
            )
            alias_map = _collect_alias_map(expression, cte_names)
        except Exception:
            alias_map = _collect_alias_map(expression, cte_names)

    tables = _extract_tables(expression, cte_names)
    columns = _extract_columns(expression, alias_map, cte_names)
    join_keys = _extract_join_keys(expression, alias_map, cte_names)
    predicates = _extract_constant_predicates(expression, alias_map, cte_names, dialect)

    if not tables and not columns:
        return _extract_with_regex_fallback(text)

    return SqlReference(
        tables=tuple(sorted(tables)),
        columns=tuple(sorted(columns)),
        join_keys=tuple(sorted(join_keys)),
        constant_predicates=tuple(sorted(predicates)),
        parse_status="SUCCESS",
    )


def build_reference_json(
    gold_sql: str,
    evidence: str | None = None,
    *,
    db_schema: dict[str, Any] | None = None,
    dialect: str = "sqlite",
) -> dict[str, Any]:
    """由 gold SQL 生成基准参考结构。"""

    parsed = extract_sql_reference(gold_sql, db_schema=db_schema, dialect=dialect)
    source = "EVIDENCE_DERIVED" if evidence else "SQL_DERIVED"
    return {
        "gold_tables": list(parsed.tables),
        "gold_columns": list(parsed.columns),
        "gold_join_keys": list(parsed.join_keys),
        "gold_domain_predicates": list(parsed.constant_predicates),
        "gold_parse_status": parsed.parse_status,
        "reference_source": {
            "tables": "SQL_DERIVED",
            "columns": "SQL_DERIVED",
            "join_keys": "SQL_DERIVED",
            "domain_predicates": source,
        },
    }


def _normalize_ident(value: str) -> str:
    return value.strip().strip('`"[]').lower()


def _collect_cte_names(expression: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in expression.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(_normalize_ident(alias))
    return names


def _collect_alias_map(expression: exp.Expression, cte_names: set[str]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for table in expression.find_all(exp.Table):
        physical = _normalize_ident(table.name)
        if not physical or physical in cte_names:
            continue
        alias = _normalize_ident(table.alias_or_name)
        alias_map[alias] = physical
        alias_map[physical] = physical
    return alias_map


def _resolve_table_name(
    table_ref: str | None, alias_map: dict[str, str], cte_names: set[str]
) -> str | None:
    if not table_ref:
        return None
    normalized = _normalize_ident(table_ref)
    if normalized in cte_names:
        return None
    return alias_map.get(normalized, normalized)


def _column_ref(column: exp.Column, alias_map: dict[str, str], cte_names: set[str]) -> str | None:
    table = _resolve_table_name(column.table, alias_map, cte_names)
    name = column.name
    if not table or not name:
        return None
    return f"{table}.{_normalize_ident(name)}"


def _extract_tables(expression: exp.Expression, cte_names: set[str]) -> set[str]:
    tables: set[str] = set()
    for table in expression.find_all(exp.Table):
        name = _normalize_ident(table.name)
        if name and name not in cte_names:
            tables.add(name)
    return tables


def _extract_columns(
    expression: exp.Expression,
    alias_map: dict[str, str],
    cte_names: set[str],
) -> set[str]:
    columns: set[str] = set()
    for column in expression.find_all(exp.Column):
        ref = _column_ref(column, alias_map, cte_names)
        if ref:
            columns.add(ref)
    return columns


def _normalize_join_key(left: str, right: str) -> str:
    pair = sorted([left.lower(), right.lower()])
    return f"{pair[0]}={pair[1]}"


def _extract_join_keys(
    expression: exp.Expression,
    alias_map: dict[str, str],
    cte_names: set[str],
) -> set[str]:
    keys: set[str] = set()
    for join in expression.find_all(exp.Join):
        on = join.args.get("on")
        if on is not None:
            _collect_join_equalities(on, alias_map, cte_names, keys)
    return keys


def _collect_join_equalities(
    node: exp.Expression,
    alias_map: dict[str, str],
    cte_names: set[str],
    keys: set[str],
) -> None:
    if isinstance(node, exp.EQ):
        left = node.left
        right = node.right
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            left_ref = _column_ref(left, alias_map, cte_names)
            right_ref = _column_ref(right, alias_map, cte_names)
            if left_ref and right_ref:
                keys.add(_normalize_join_key(left_ref, right_ref))
        return
    for child in node.iter_expressions():
        _collect_join_equalities(child, alias_map, cte_names, keys)


def _extract_constant_predicates(
    expression: exp.Expression,
    alias_map: dict[str, str],
    cte_names: set[str],
    dialect: str,
) -> set[str]:
    predicates: set[str] = set()
    comparison_types = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.In)
    for clause in expression.find_all(exp.Where, exp.Having):
        for node in clause.find_all(*comparison_types):
            predicate = _predicate_from_comparison(node, alias_map, cte_names, dialect)
            if predicate:
                predicates.add(predicate)
    return predicates


def _predicate_from_comparison(
    node: exp.Expression,
    alias_map: dict[str, str],
    cte_names: set[str],
    dialect: str,
) -> str | None:
    if isinstance(node, exp.In):
        column = node.this
        if not isinstance(column, exp.Column):
            return None
        ref = _column_ref(column, alias_map, cte_names)
        if not ref:
            return None
        values = [_format_literal(item, dialect) for item in node.expressions]
        if not values:
            return None
        if len(values) == 1:
            return f"{ref}={values[0]}"
        return f"{ref} in ({', '.join(values)})"

    if not isinstance(node, exp.EQ | exp.NEQ | exp.GT | exp.GTE | exp.LT | exp.LTE | exp.Like):
        return None

    left = node.left
    right = node.right
    if isinstance(left, exp.Column) and _is_constant_expr(right):
        ref = _column_ref(left, alias_map, cte_names)
        if not ref:
            return None
        return f"{ref}{_operator_token(node)}{_format_literal(right, dialect)}"
    if isinstance(right, exp.Column) and _is_constant_expr(left):
        ref = _column_ref(right, alias_map, cte_names)
        if not ref:
            return None
        return f"{ref}{_operator_token(node)}{_format_literal(left, dialect)}"
    return None


def _operator_token(node: exp.Expression) -> str:
    if isinstance(node, exp.NEQ):
        return "<>"
    if isinstance(node, exp.GT):
        return ">"
    if isinstance(node, exp.GTE):
        return ">="
    if isinstance(node, exp.LT):
        return "<"
    if isinstance(node, exp.LTE):
        return "<="
    if isinstance(node, exp.Like):
        return " like "
    return "="


def _is_constant_expr(node: exp.Expression | None) -> bool:
    if node is None:
        return False
    if isinstance(node, exp.Literal):
        return True
    if isinstance(node, exp.Neg | exp.Not):
        return _is_constant_expr(node.this)
    return False


def _format_literal(node: exp.Expression, dialect: str) -> str:
    if isinstance(node, exp.Literal):
        if node.is_string:
            return repr(str(node.name).lower())
        return str(node.name).lower()
    return node.sql(dialect=dialect).strip().lower()


def _extract_with_regex_fallback(sql: str) -> SqlReference:
    text = _SQL_COMMENT_PATTERN.sub(" ", sql)
    alias_map = _alias_map_from_regex(text)
    tables = sorted(
        {_normalize_ident(match.group(1).split(".")[-1]) for match in _TABLE_PATTERN.finditer(text)}
    )
    columns = sorted(
        {
            _resolve_regex_column(match.group(1), match.group(2), alias_map)
            for match in _COLUMN_PATTERN.finditer(text)
        }
    )
    join_keys: set[str] = set()
    for join_match in _JOIN_PATTERN.finditer(text):
        for left, right in re.findall(
            r"([A-Za-z_]\w*\.[A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*\.[A-Za-z_]\w*)",
            join_match.group(1),
        ):
            left_alias, left_column = left.split(".", 1)
            right_alias, right_column = right.split(".", 1)
            left_ref = _resolve_regex_column(left_alias, left_column, alias_map)
            right_ref = _resolve_regex_column(right_alias, right_column, alias_map)
            join_keys.add(_normalize_join_key(left_ref, right_ref))
    predicates = sorted(
        {_resolve_regex_predicate(match, alias_map) for match in _PREDICATE_PATTERN.finditer(text)}
    )
    return SqlReference(
        tables=tuple(tables),
        columns=tuple(columns),
        join_keys=tuple(sorted(join_keys)),
        constant_predicates=tuple(predicates),
        parse_status="FALLBACK",
    )


def _alias_map_from_regex(text: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for match in re.finditer(
        r"\b(?:from|join)\s+([`\"\[]?[A-Za-z_][\w.]*[`\"\]]?)\s+(?:as\s+)?([A-Za-z_]\w*)\b",
        text,
        flags=re.I,
    ):
        physical = _normalize_ident(match.group(1).split(".")[-1])
        alias = _normalize_ident(match.group(2))
        if physical and alias:
            alias_map[alias] = physical
            alias_map[physical] = physical
    return alias_map


def _resolve_regex_column(alias: str, column: str, alias_map: dict[str, str]) -> str:
    table = alias_map.get(_normalize_ident(alias), _normalize_ident(alias))
    return f"{table}.{_normalize_ident(column)}"


def _resolve_regex_predicate(match: re.Match[str], alias_map: dict[str, str]) -> str:
    left = match.group(1)
    op = match.group(2).lower()
    value = match.group(3).strip().lower()
    if "." in left:
        alias, column = left.split(".", 1)
        ref = _resolve_regex_column(alias, column, alias_map)
    else:
        ref = _normalize_ident(left)
    return f"{ref}{op}{value}"
