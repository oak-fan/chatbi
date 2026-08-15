"""ChatBI 问数各阶段 Prompt 模板。"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from cogmait_shared.core.naming import camel_to_snake_dict

from .....constants.chatbi.datasource import CHATBI_EXECUTE_SQL_MAX_ROWS
from .....constants.chatbi.query import (
    CHATBI_CLARIFICATION_SKIPPED_MARKER,
    CHATBI_INTENT_JSON_FIELD_BRIEF,
    CHATBI_INTENT_JSON_FIELD_CHOICE,
    CHATBI_INTENT_JSON_FIELD_CLARIFICATION_QUESTION,
    CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID,
    CHATBI_INTENT_JSON_FIELD_INTENT,
    CHATBI_INTENT_JSON_FIELD_OPTIONS,
)
from .....domain.system.chatbi import ChatbiQueryIntent
from ..business_knowledge_service import format_business_knowledge_display

_INTENT_CHOICES_TEXT = " | ".join(item.value for item in ChatbiQueryIntent)
_VALID_INTENT_CHOICES = frozenset(item.value for item in ChatbiQueryIntent)


def json_safe_value(value: Any) -> Any:
    """将查询单元格值转为 JSON 可序列化类型。"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def json_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(key): json_safe_value(val) for key, val in row.items()} for row in rows]


def dumps_json_safe(value: Any) -> str:
    """json.dumps 包装，对未预先转换的值做兜底。"""
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _format_business_knowledge_bullet(item: dict[str, Any]) -> str:
    display = item.get("display_content")
    if isinstance(display, str) and display.strip():
        return f"- {display.strip()}"
    return f"- {format_business_knowledge_display(item)}"


def _split_question_and_evidence(question: str) -> tuple[str, str | None]:
    text = (question or "").strip()
    marker = "\n\n# Evidence\n"
    if marker in text:
        base, evidence = text.split(marker, 1)
        evidence_text = evidence.strip()
        return base.strip(), evidence_text or None
    legacy = "\n\nevidence:\n"
    if legacy in text:
        base, evidence = text.split(legacy, 1)
        evidence_text = evidence.strip()
        return base.strip(), evidence_text or None
    return text, None


_INTENT_JSON_FIELD_NAMES = (
    f"{CHATBI_INTENT_JSON_FIELD_BRIEF}、{CHATBI_INTENT_JSON_FIELD_CHOICE}、"
    f"{CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID}、"
    f"{CHATBI_INTENT_JSON_FIELD_CLARIFICATION_QUESTION}、"
    f"{CHATBI_INTENT_JSON_FIELD_OPTIONS}"
)
_INTENT_DS_ID_WHEN_REQUIRED = (
    f"{CHATBI_INTENT_JSON_FIELD_CHOICE}={ChatbiQueryIntent.QUERY.value} 或 "
    f"{ChatbiQueryIntent.CLARIFICATION.value} 时必填"
)
_INTENT_DS_ID_WHEN_NULL = (
    f"{CHATBI_INTENT_JSON_FIELD_CHOICE}={ChatbiQueryIntent.UNRELATED.value} 时为 null"
)
_INTENT_CLARIFICATION_Q_HINT = (
    f"{CHATBI_INTENT_JSON_FIELD_CHOICE}={ChatbiQueryIntent.CLARIFICATION.value} "
    "时追问用户，否则空字符串"
)
_INTENT_CLARIFICATION_OPTIONS_HINT = (
    f"{CHATBI_INTENT_JSON_FIELD_CHOICE}={ChatbiQueryIntent.CLARIFICATION.value} "
    "时的可选项，可为空数组"
)
_INTENT_RESUME_AFTER_SKIP = (
    f"尽量合理默认后输出 {ChatbiQueryIntent.QUERY.value}，"
    f"仍无法确定则 {ChatbiQueryIntent.CLARIFICATION.value}。"
)

INTENT_SYSTEM = f"""
# 角色
你是 ChatBI 问数意图识别助手。根据用户问题、当前时间、数据源列表与业务知识，判断下一步。

# 输出要求（必须严格遵守）
1. 只输出一个合法 JSON 对象，不要 Markdown、不要其它文字
2. 字段名必须为英文：{_INTENT_JSON_FIELD_NAMES}
3. {CHATBI_INTENT_JSON_FIELD_CHOICE} 只能取：{_INTENT_CHOICES_TEXT}
4. {CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID} 必须为「# 数据源列表」中的整数 id；
   {_INTENT_DS_ID_WHEN_REQUIRED}；{_INTENT_DS_ID_WHEN_NULL}

# JSON 结构
{{
  "{CHATBI_INTENT_JSON_FIELD_BRIEF}": "一句话说明判断理由",
  "{CHATBI_INTENT_JSON_FIELD_CHOICE}": "{_INTENT_CHOICES_TEXT}",
  "{CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID}": 123,
  "{CHATBI_INTENT_JSON_FIELD_CLARIFICATION_QUESTION}": "{_INTENT_CLARIFICATION_Q_HINT}",
  "{CHATBI_INTENT_JSON_FIELD_OPTIONS}": ["{_INTENT_CLARIFICATION_OPTIONS_HINT}"]
}}

# 选择判定
## {ChatbiQueryIntent.UNRELATED.value}
用户问题与全部数据源的表名、业务主题完全无关（闲聊、其它系统等）。

## {ChatbiQueryIntent.CLARIFICATION.value}
以下任一项无法从问题与业务知识中唯一确定，须在 clarification_question / options 中向用户追问：
- 统计指标及计算口径（算什么、按什么公式）
- 分组/筛选维度（按什么维度看）
- 时间范围或统计周期（何时、哪段时间；可结合当前时间解析相对表述）
- 多种合理解读且业务知识无法消除歧义

## {ChatbiQueryIntent.QUERY.value}
已选定 datasource_id；上述要素已明确，或可由业务知识合理唯一默认，可进入 SQL 生成。

# 澄清续跑
用户消息含「# 澄清续跑」时，阅读追问、选项与用户回答；
若用户回答为「{CHATBI_CLARIFICATION_SKIPPED_MARKER}」表示跳过澄清，
{_INTENT_RESUME_AFTER_SKIP}

# 输出示例
{{"{CHATBI_INTENT_JSON_FIELD_BRIEF}":"用户问题统计指标和筛选维度清晰，时间范围明确，可转化为SQL语句","{CHATBI_INTENT_JSON_FIELD_CHOICE}":"{ChatbiQueryIntent.QUERY.value}","{CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID}":1,"{CHATBI_INTENT_JSON_FIELD_CLARIFICATION_QUESTION}":"","{CHATBI_INTENT_JSON_FIELD_OPTIONS}":[]}}
{{"{CHATBI_INTENT_JSON_FIELD_BRIEF}":"用户没有明确时间范围","{CHATBI_INTENT_JSON_FIELD_CHOICE}":"{ChatbiQueryIntent.CLARIFICATION.value}","{CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID}":1,"{CHATBI_INTENT_JSON_FIELD_CLARIFICATION_QUESTION}":"请问您查询的时间范围是多少？","{CHATBI_INTENT_JSON_FIELD_OPTIONS}":[]}}
{{"{CHATBI_INTENT_JSON_FIELD_BRIEF}":"用户问题与现有数据源无关","{CHATBI_INTENT_JSON_FIELD_CHOICE}":"{ChatbiQueryIntent.UNRELATED.value}","{CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID}":null,"{CHATBI_INTENT_JSON_FIELD_CLARIFICATION_QUESTION}":"","{CHATBI_INTENT_JSON_FIELD_OPTIONS}":[]}}
""".strip()

TEXT2SQL_SYSTEM_TEMPLATE = """
# 角色
你是 Text-to-SQL 专家。根据用户问题、数据库结构与 Evidence 生成正确 SQL。

# 基本规范
- 严格遵循 {db_type} 语法
- 只读 SELECT，不含 DDL/DML
- 输出 JSON：{{"sql": "SELECT ..."}}

# 核心规则
1. **列存在性检查（最重要）**：SELECT 和 WHERE 中的每一列必须在你选择的表中有定义。先列出需要的列，再逐列确认所在表，最后才写 FROM/JOIN。如果某列不在表中就换表。
2. **Evidence 中提到的表名和列名必须使用**，不要换成同名的其他列。
3. **JOIN 必须通过 foreign_keys 中的外键关系**。只 JOIN 需要的表。连接条件与 foreign_keys 一致。
4. **筛选值必须与列样本值完全一致**（大小写敏感）。不猜值。Evidence 格式转换必须执行。
5. **「每 X 的最高/最低/最多/最少」= GROUP BY X + 聚合函数 + ORDER BY + LIMIT 1**，不要直接用 MAX/MIN。
6. **比例**用 CAST(分子 AS REAL) / 分母 或 SUM(CASE WHEN ...) / COUNT(*)。
7. 不要因为问题中出现某个词就自动使用对应表（如"customer"）。先确认需要的列在哪个表中。

# 当前时间
{current_time}

# 数据库信息
- 数据库类型：{db_type}
- 结构描述：
{db_description}
""".strip()

TEXT2SQL_COT_APPENDIX = """
# Prompting mode: chain-of-thought candidate
You may include a "reasoning" field showing key reasoning steps.
Focus on: table identification, join paths from foreign keys, filter mapping,
aggregation grain, grouping columns, ordering, and output shape.

# Output example
{
  "reasoning": "1) Tables: ... 2) Joins: ... 3) Filters: ... 4) Group/Agg: ...",
  "sql": "SELECT * FROM table"
}
""".strip()

TEXT2SQL_DECOMPOSITION_APPENDIX = """
# Prompting mode: problem-decomposition candidate
This section overrides the JSON field restriction above for this candidate only.
You may include one concise "decomposition" field describing the sub-problems, but the final
JSON object must still contain the "sql" field and must not contain Markdown or prose outside JSON.
Decompose the question into intent, required tables, joins, filters, aggregation,
and final projection.

# Output example
{"decomposition": ["identify tables", "apply filters", "aggregate"], "sql": "SELECT * FROM table"}
""".strip()

AGENTAR_SQL_SELECTOR_SYSTEM_TEMPLATE = """
# Role
You are a Text-to-SQL tournament judge. Given a user question, database schema, business
knowledge, and two candidate SQL answers with execution previews, decide which SQL better
answers the question.

# Database
- Type: {db_type}
- Current time: {current_time}
- Schema:
{db_description}

# Judging rules
1. Prefer the SQL that better matches the question semantics, schema, business knowledge,
   clarification context, filters, joins, aggregation, grouping, ordering, and limit.
2. Execution success is useful evidence, but do not choose an executable SQL if it clearly
   answers the wrong question.
3. Prefer candidates whose execution preview row_count and column set better match the
   question grain (e.g. single aggregate vs detail rows). Empty results are weak evidence
   unless the question expects zero rows.
4. If both SQLs are semantically equivalent for the question, return "tie".
5. Be concise. Do not reveal a long chain of thought.

# Output requirement
Return exactly one JSON object, no Markdown and no extra prose:
{{"winner": "A|B|tie", "confidence": 0.0, "reason": "brief reason"}}
""".strip()

SQL_FIX_ERROR_SYSTEM = (
    "上次 SQL 执行失败。请根据错误信息与表结构修正 SQL，只输出单条 SELECT，不要解释。"
)

SQL_VALIDATE_SYSTEM = """
Validate the SQL. Check:
1. Required tables joined? No extra tables?
2. Filters use correct column names and values (match column sample values exactly)?
3. For "highest/lowest per X": is there GROUP BY X + aggregate + ORDER BY + LIMIT?
4. Evidence date format and formulas applied correctly?
5. Only real columns from schema used?

Output: {"sql": "corrected SELECT"} (unchanged if OK)
""".strip()

SUMMARY_SYSTEM = (
    "你是数据分析助手。根据用户问题、执行的 SQL 与查询结果样本，"
    "用户界面可看到完整返回行；"
    "但是如果数据过多，你只能看到「结果行数说明」中的行数。"
    "根据你看到的信息，给出结论与关键发现（3-6 句），回答用户问题。\n"
    "如果有截断，不要编造你没看到的数据。"
)


def build_summary_user_content(
    *,
    question: str,
    sql: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    row_count: int,
    preview_row_count: int,
    result_truncated: bool,
    preview_max_rows: int,
    execute_max_rows: int = CHATBI_EXECUTE_SQL_MAX_ROWS,
) -> str:
    """组装结果总结 user 内容（含总行数、样本行数与截断说明）。"""
    sample_rows = json_safe_rows(rows[:preview_max_rows])
    preview = {"columns": columns, "rows": sample_rows}
    lines = [
        "# 用户问题",
        question.strip(),
        "",
        "# SQL",
        sql.strip(),
        "",
        "# 结果行数说明",
        f"- 本次查询返回给用户的数据共 {row_count} 行",
        f"- 你（摘要模型）看到的是前 {preview_row_count} 行",
    ]
    if result_truncated:
        lines.append(
            f"- SQL 执行结果已截断：仅返回前 {execute_max_rows} 行，"
            "数据库中可能还有更多行，勿当作已统计全部数据"
        )
    elif row_count > preview_row_count:
        lines.append(f"- 数据已被截断，完整 {row_count} 行已由用户在前端查看")
    lines.extend(
        [
            "",
            f"# 结果样本（前 {preview_row_count} 行）",
            dumps_json_safe(preview),
        ]
    )
    return "\n".join(lines)


def _parse_datasource_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        ds_id = int(value)
        return ds_id if ds_id > 0 else None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    if text.isdigit():
        ds_id = int(text)
        return ds_id if ds_id > 0 else None
    return None


def datasource_description_from_db_schema(db_schema: Any) -> str | None:
    """从 db_schema 根级 description 提取数据源业务介绍。"""
    if not isinstance(db_schema, dict):
        return None
    text = str(db_schema.get("description") or "").strip()
    return text or None


def table_names_from_db_schema(db_schema: Any) -> list[str]:
    """从 db_schema 提取表名列表。"""
    if not isinstance(db_schema, dict):
        return []
    names: list[str] = []
    for table in db_schema.get("tables") or []:
        if not isinstance(table, dict):
            continue
        name = str(table.get("table_name") or "").strip()
        if name:
            names.append(name)
    return names


def format_datasource_line(ds: dict[str, Any]) -> str:
    """格式化单条数据源（供意图识别列表）。"""
    ds_id = ds.get("id")
    name = str(ds.get("name") or "").strip()
    desc = str(ds.get("description") or "").strip()
    tables = ds.get("table_names") or []
    table_text = ",".join(str(t) for t in tables) if tables else "(无)"
    parts = [f"id={ds_id}", f"name={name}"]
    if desc:
        parts.append(f"介绍={desc}")
    parts.append(f"表={table_text}")
    return "- " + " ".join(parts)


def build_effective_question_after_clarification(
    *,
    rewritten_question: str,
    clarification_question: str | None,
    user_clarification_answer: str | None,
) -> str:
    """将系统追问与用户澄清并入后续检索/生成用的问句。"""
    parts = [rewritten_question.strip()]
    cq = (clarification_question or "").strip()
    if cq:
        parts.append(f"系统追问：{cq}")
    ans = (user_clarification_answer or "").strip()
    if ans:
        parts.append(f"用户澄清：{ans}")
    return "\n".join(parts)


def build_intent_user_content(
    *,
    question: str,
    rewritten_question: str,
    current_time: str,
    datasource_list: list[dict[str, Any]],
    business_knowledge: list[dict[str, Any]],
    is_clarification_resume: bool = False,
    clarification_question: str | None = None,
    clarification_options: list[str] | None = None,
    user_clarification_answer: str | None = None,
) -> str:
    lines = [
        "# 当前时间",
        current_time,
        "",
        "# 用户问题",
        f"原问：{question}",
        f"改写：{rewritten_question}",
    ]
    if is_clarification_resume:
        lines.extend(["", "# 澄清续跑"])
        cq = (clarification_question or "").strip()
        if cq:
            lines.append(f"追问：{cq}")
        lines.append("选项：")
        options = clarification_options or []
        if options:
            for opt in options:
                lines.append(f"- {opt}")
        else:
            lines.append("- (无)")
        ans = (user_clarification_answer or "").strip()
        if ans:
            lines.append(f"用户回答：{ans}")
    lines.extend(["", "# 数据源列表"])
    if datasource_list:
        for ds in datasource_list:
            lines.append(format_datasource_line(ds))
    else:
        lines.append("- (无)")
    lines.extend(["", "# 业务知识"])
    if business_knowledge:
        for item in business_knowledge:
            lines.append(_format_business_knowledge_bullet(item))
    else:
        lines.append("- (无)")
    return "\n".join(lines)


def normalize_intent_result(data: dict[str, Any]) -> dict[str, Any]:
    """将模型 JSON 规范为内部字段，choice → intent 代码，datasource_id 为整数。"""
    parsed = camel_to_snake_dict(data)

    choice_raw = (
        parsed.get(CHATBI_INTENT_JSON_FIELD_CHOICE)
        or parsed.get(CHATBI_INTENT_JSON_FIELD_INTENT)
        or ""
    )
    choice_text = str(choice_raw).strip().lower()
    if choice_text not in _VALID_INTENT_CHOICES:
        choices = "、".join(sorted(_VALID_INTENT_CHOICES))
        msg = f"intent choice 非法：{choice_text or '(empty)'}，合法值：{choices}"
        raise ValueError(msg)
    intent_code = choice_text

    brief = _optional_text(
        parsed.get(CHATBI_INTENT_JSON_FIELD_BRIEF)
        or parsed.get("brief_explanation")
        or parsed.get("message")
    )
    ds_id = _parse_datasource_id(
        parsed.get(CHATBI_INTENT_JSON_FIELD_DATASOURCE_ID) or parsed.get("datasource")
    )

    return {
        "intent": intent_code,
        "choice": intent_code,
        "brief_explanation": brief,
        "datasource_id": ds_id,
        "clarification_question": parsed.get(CHATBI_INTENT_JSON_FIELD_CLARIFICATION_QUESTION),
        "options": parsed.get(CHATBI_INTENT_JSON_FIELD_OPTIONS),
        "message": brief,
    }


def intent_detail_from_result(intent_result: dict[str, Any]) -> dict[str, Any]:
    """从意图 JSON 提取对外展示的解析字段。"""
    ds_id = intent_result.get("datasource_id")
    return {
        "brief_explanation": _optional_text(intent_result.get("brief_explanation")),
        "choice": _optional_text(intent_result.get("choice")),
        "datasource_id": str(ds_id) if ds_id is not None else None,
        "message": _optional_text(intent_result.get("message")),
    }


def build_clarification_dialogue_for_text2sql(
    *,
    clarification_question: str | None,
    user_clarification_answer: str | None,
    clarification_skipped: bool = False,
) -> str | None:
    """组装 text2sql 用的澄清对话记录（含跳过）。"""
    cq = (clarification_question or "").strip()
    ans = (user_clarification_answer or "").strip()
    if clarification_skipped and not ans:
        ans = CHATBI_CLARIFICATION_SKIPPED_MARKER
    if not cq and not ans:
        return None
    lines: list[str] = []
    if cq:
        lines.append(f"追问：{cq}")
    if ans:
        lines.append(f"用户回答：{ans}")
    return "\n".join(lines)


def text2sql_clarification_kwargs(
    *,
    clarification_question: str | None = None,
    user_clarification_answer: str | None = None,
) -> dict[str, str | None]:
    """text2sql / sql_fix 用的澄清上下文字段。"""
    return {
        "clarification_question": _optional_text(clarification_question),
        "user_clarification_answer": _optional_text(user_clarification_answer),
    }


def _append_clarification_lines(
    parts: list[str],
    *,
    clarification_question: str | None,
    user_clarification_answer: str | None,
) -> None:
    if not clarification_question and not user_clarification_answer:
        return
    parts.append("# 澄清补充")
    if clarification_question:
        parts.append(f"追问={clarification_question}")
    if user_clarification_answer:
        parts.append(f"回答={user_clarification_answer}")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "无", "n/a"}:
        return None
    return text


def build_text2sql_system_prompt(
    *,
    db_type: str,
    db_description: str,
    current_time: str,
    prompt_format: str = "direct",
) -> str:
    """组装 text2sql 系统提示词（注入库类型、当前时间与结构描述）。"""
    base = TEXT2SQL_SYSTEM_TEMPLATE.format(
        db_type=db_type.strip() or "PostgreSQL",
        db_description=db_description.strip() or "(无)",
        current_time=current_time.strip(),
    )
    if prompt_format == "chain_of_thought":
        return f"{base}\n\n{TEXT2SQL_COT_APPENDIX}"
    if prompt_format == "problem_decomposition":
        return f"{base}\n\n{TEXT2SQL_DECOMPOSITION_APPENDIX}"
    return base


def build_text2sql_user_content(
    *,
    question: str,
    qsql_examples: list[dict[str, str]],
    business_knowledge: list[dict[str, Any]],
    clarification_question: str | None = None,
    user_clarification_answer: str | None = None,
    clarification_dialogue: str | None = None,
    value_founding_text: str | None = None,
    rag_knowledge_hits: list[dict[str, Any]] | None = None,
) -> str:
    user_question, evidence = _split_question_and_evidence(question)
    parts = ["# 用户问题", user_question.strip() or question.strip()]
    if evidence:
        parts.extend(["", "# Evidence", evidence])
    if value_founding_text:
        parts.extend(["", "# Verified database literal values", value_founding_text.strip()])
    if rag_knowledge_hits:
        parts.extend(["", "# Database schema knowledge"])
        parts.append("The following are relevant schema descriptions retrieved from the knowledge store:")
        for hit in rag_knowledge_hits:
            table = hit.get("table_name", "")
            content = hit.get("content", "")
            score = hit.get("score", 0)
            parts.append(f"\n## {table} (relevance: {score:.2f})\n{content}")
    dialogue = (clarification_dialogue or "").strip()
    if dialogue:
        parts.extend(["", "# 澄清对话", dialogue])
    _append_clarification_lines(
        parts,
        clarification_question=clarification_question,
        user_clarification_answer=user_clarification_answer,
    )
    if business_knowledge:
        parts.extend(["", "# 业务知识"])
        for item in business_knowledge:
            parts.append(_format_business_knowledge_bullet(item))
    if qsql_examples:
        parts.extend(["", "# 相似问数样例"])
        parts.append("样例仅用于参考 SQL 结构与写法，不要复制不属于当前数据库信息的表名或字段名。")
        for ex in qsql_examples:
            parts.append(f"Q: {ex.get('question')}\nSQL: {ex.get('sql_body')}")
    return "\n".join(parts)


def build_agentar_sql_selector_system_prompt(
    *,
    db_type: str,
    db_description: str,
    current_time: str,
) -> str:
    return AGENTAR_SQL_SELECTOR_SYSTEM_TEMPLATE.format(
        db_type=db_type.strip() or "PostgreSQL",
        db_description=db_description.strip() or "(none)",
        current_time=current_time.strip(),
    )


def build_agentar_sql_selector_user_content(
    *,
    question: str,
    business_knowledge: list[dict[str, Any]],
    candidate_a: dict[str, Any],
    candidate_b: dict[str, Any],
    clarification_dialogue: str | None = None,
) -> str:
    parts = ["# User question", question.strip()]
    dialogue = (clarification_dialogue or "").strip()
    if dialogue:
        parts.extend(["", "# Clarification dialogue", dialogue])
    if business_knowledge:
        parts.extend(["", "# Business knowledge"])
        for item in business_knowledge:
            parts.append(_format_business_knowledge_bullet(item))
    parts.extend(
        [
            "",
            "# Candidate A",
            dumps_json_safe(candidate_a),
            "",
            "# Candidate B",
            dumps_json_safe(candidate_b),
            "",
            "Begin. Judge which candidate better answers the question.",
            "[no prose][output json only]",
        ]
    )
    return "\n".join(parts)


def build_sql_fix_user_content(
    *,
    question: str,
    sql: str,
    error_message: str | None,
    schema_text: str,
    clarification_question: str | None = None,
    user_clarification_answer: str | None = None,
) -> str:
    parts = ["# 用户问题", question]
    _append_clarification_lines(
        parts,
        clarification_question=clarification_question,
        user_clarification_answer=user_clarification_answer,
    )
    parts.extend(["", f"上次SQL={sql}", "", "# 表结构", schema_text, f"错误={error_message}"])
    return "\n".join(parts)


def build_sql_validate_user_content(
    *,
    question: str,
    sql: str,
    schema_text: str,
    validate_context: dict[str, Any],
    clarification_question: str | None = None,
    user_clarification_answer: str | None = None,
) -> str:
    parts = ["# 用户问题", question]
    _append_clarification_lines(
        parts,
        clarification_question=clarification_question,
        user_clarification_answer=user_clarification_answer,
    )
    parts.extend(
        [
            "",
            "# 待 validate SQL",
            sql,
            "",
            "# 表结构",
            schema_text,
            "",
            "# SQL validate 结果",
            dumps_json_safe(validate_context),
        ]
    )
    return "\n".join(parts)


def parse_text2sql_response(content: str) -> dict[str, Any]:
    """解析 text2sql JSON 响应，返回 sql 及由 sql 是否非空推导的 success。"""
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        msg = "text2sql 响应必须为 JSON 对象"
        raise ValueError(msg)
    parsed = camel_to_snake_dict(data)
    sql = parsed.get("sql")
    sql_str = str(sql).strip() if isinstance(sql, str) and str(sql).strip() else None
    return {
        "success": bool(sql_str),
        "sql": sql_str,
    }


def parse_agentar_sql_selector_response(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        msg = "agentar selector response must be a JSON object"
        raise ValueError(msg)
    parsed = camel_to_snake_dict(data)
    winner = str(parsed.get("winner") or "").strip().upper()
    if winner == "TIE":
        winner = "tie"
    if winner not in {"A", "B", "tie"}:
        msg = "agentar selector winner must be A, B, or tie"
        raise ValueError(msg)
    confidence_raw = parsed.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    return {
        "winner": winner,
        "confidence": confidence,
        "reason": str(parsed.get("reason") or "").strip(),
    }


def parse_intent_response(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        msg = "intent 响应必须为 JSON 对象"
        raise ValueError(msg)
    return normalize_intent_result(data)


def extract_sql_from_llm(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text.strip()
