"""字典项编码相关的工具方法。"""

from __future__ import annotations

from typing import Any

MAX_TEXT_DICT_VALUE_LENGTH = 40


def normalize_dict_value(value: Any, *, field_name: str = "value") -> str:
    """将外部输入归一化为 item_code 字符串。"""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须为字符串")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空白")
    if text.isdigit():
        raise ValueError(f"{field_name} 不能为纯数字字符串")
    if len(text) > MAX_TEXT_DICT_VALUE_LENGTH:
        raise ValueError(
            f"{field_name} 长度不能超过 {MAX_TEXT_DICT_VALUE_LENGTH}",
        )
    return text


def ensure_dict_value_str(value: Any) -> str:
    """返回标准化后的 item_code，用于所有比较/唯一性校验。"""
    return normalize_dict_value(value)
