"""共享的文件业务类型定义。"""

from __future__ import annotations

from enum import StrEnum


class FileBusinessType(StrEnum):
    """跨服务共享的文件业务类型，单服务专用类型不要放入 shared。"""

    GENERAL = "GENERAL"
    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"
    SYSTEM_RESOURCE = "SYSTEM_RESOURCE"
    CONVERSATION_ATTACHMENT = "CONVERSATION_ATTACHMENT"
    AGENT_OUTPUT = "AGENT_OUTPUT"


FILE_BUSINESS_TYPE_DESCRIPTIONS: dict[FileBusinessType, str] = {
    FileBusinessType.GENERAL: "通用文件",
    FileBusinessType.KNOWLEDGE_BASE: "知识库文件",
    FileBusinessType.SYSTEM_RESOURCE: "系统资源",
    FileBusinessType.CONVERSATION_ATTACHMENT: "会话附件",
    FileBusinessType.AGENT_OUTPUT: "Agent 产物",
}


class FileParserType(StrEnum):
    """文档解析处理器类型，供 parser 字段使用。"""

    PDF = "pdf"
    OFFICE = "office"
    IMAGE = "image"
    AUDIO = "audio"
    TEXT = "text"


FILE_PARSER_TYPE_DESCRIPTIONS: dict[FileParserType, str] = {
    FileParserType.PDF: "PDF 处理器",
    FileParserType.OFFICE: "Office 文档处理器",
    FileParserType.IMAGE: "图片处理器",
    FileParserType.AUDIO: "音频处理器",
    FileParserType.TEXT: "纯文本处理器",
}


def describe_business_type(business_code: FileBusinessType) -> str:
    """返回业务类型说明文本。"""

    return FILE_BUSINESS_TYPE_DESCRIPTIONS.get(business_code, "")


__all__ = [
    "FileBusinessType",
    "FILE_BUSINESS_TYPE_DESCRIPTIONS",
    "FileParserType",
    "FILE_PARSER_TYPE_DESCRIPTIONS",
    "describe_business_type",
]
