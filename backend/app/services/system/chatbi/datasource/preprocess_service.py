"""ChatBI 数据源结构补全：调用大模型写入列级 description。"""

from __future__ import annotations

import json
import re
from typing import cast

from .....constants.chat import CHAT_MESSAGE_ROLE_SYSTEM, CHAT_MESSAGE_ROLE_USER
from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from .....domain.system.llm import CompletionRequest, CompletionResponse, Message
from ...llm_service import LLMService, LLMServiceError
from ..datasource_errors import ChatbiDatasourceServiceError


def _extract_json_payload(text: str) -> str:
    """去掉首尾空白；剥离常见 Markdown ```json 代码块包裹。"""
    stripped = text.strip()
    fence_match = re.match(
        r"^```(?:json)?\s*\n?(.*)\n?```\s*$",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fence_match:
        return fence_match.group(1).strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def parse_column_description_map(text: str) -> tuple[str, dict[str, str]]:
    """解析 LLM 返回的整段 JSON，得到库级描述与「表.列」→ 列描述映射。"""
    try:
        payload = json.loads(_extract_json_payload(text))
    except json.JSONDecodeError as exc:
        msg = "列描述输出必须为 JSON"
        raise ValueError(msg) from exc
    if not isinstance(payload, dict):
        msg = "JSON 根必须为对象"
        raise ValueError(msg)

    ds_raw = payload.get("datasource_description", "")
    if ds_raw is None:
        datasource_description = ""
    elif not isinstance(ds_raw, str):
        msg = "datasource_description 必须为字符串"
        raise ValueError(msg)
    else:
        datasource_description = ds_raw.strip()

    cols_raw = payload.get("columns")
    if not isinstance(cols_raw, dict):
        msg = "columns 必须为对象"
        raise ValueError(msg)

    column_map: dict[str, str] = {}
    for key, value in cols_raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, str):
            continue
        v = value.strip()
        if v:
            column_map[key.strip()] = v

    return datasource_description, column_map


_FEW_SHOT_SYSTEM = (
    "你是数据库业务语义标注助手。根据用户给出的表列元数据摘要，"
    "只返回**一整段合法 JSON 文本**（从第一个字符 `{` 到最后一个 `}`，"
    "中间不要 Markdown 代码块、不要前后解释文字）。\n"
    "\n"
    "JSON 形状（字段名固定、勿改名）：\n"
    "{\n"
    '  "datasource_description": "整库一句话业务说明",\n'
    '  "columns": {\n'
    '    "表名.列名": "该列业务含义",\n'
    '    "另一表.另一列": "含义"\n'
    "  }\n"
    "}\n"
    "\n"
    "规则：\n"
    "- `columns` 的键必须是「表名.列名」，与用户输入中出现的表名、列名一致。\n"
    "- 尽量为每一列填写含义；缺失的键将保留为空描述。\n"
    "- 不要输出 type、constraints、samples 等重复字段。"
)


class ChatbiSchemaEnrichmentService:
    """调用大模型补全 description，由代码合并进 db_schema。"""

    def __init__(self, *, llm_service: LLMService) -> None:
        self._llm = llm_service

    async def enrich_structure(self, structure: ChatbiDbSchemaRecord) -> ChatbiDbSchemaRecord:
        """调用大模型补全库/列描述并写回结构对象。"""
        user_content = structure.build_llm_context_summary()
        req = CompletionRequest(
            messages=[
                Message(role=CHAT_MESSAGE_ROLE_SYSTEM, content=_FEW_SHOT_SYSTEM),
                Message(role=CHAT_MESSAGE_ROLE_USER, content=user_content),
            ],
            temperature=0.0,
        )
        try:
            response = cast(
                CompletionResponse,
                await self._llm.acompletion(req),
            )
        except LLMServiceError as exc:
            raise ChatbiDatasourceServiceError.system_error(
                f"列描述补全失败：{exc.message}"
            ) from exc
        if not hasattr(response, "choices") or not response.choices:
            raise ChatbiDatasourceServiceError.system_error("列描述补全失败：模型返回为空")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ChatbiDatasourceServiceError.system_error("列描述补全失败：模型返回空内容")
        try:
            datasource_desc, column_map = parse_column_description_map(content)
        except ValueError as exc:
            raise ChatbiDatasourceServiceError.bad_request(str(exc)) from exc
        if not column_map:
            raise ChatbiDatasourceServiceError.bad_request("列描述补全失败：未返回有效的列描述")
        structure.apply_descriptions(
            datasource_description=datasource_desc,
            column_descriptions=column_map,
        )
        return structure


__all__ = ["ChatbiSchemaEnrichmentService", "parse_column_description_map"]
