"""跨服务共享的数据库异常别名。"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import exc as sa_exc

DatabaseError = sa_exc.SQLAlchemyError
IntegrityError = sa_exc.IntegrityError


def integrity_error_has_token(exc: BaseException, tokens: Iterable[str]) -> bool:
    """判断数据库完整性错误是否命中指定约束名或错误消息片段。"""

    normalized_tokens = {str(token).lower() for token in tokens if str(token).strip()}
    if not normalized_tokens:
        return False
    original = getattr(exc, "orig", None)
    diag = getattr(original, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name and str(constraint_name).lower() in normalized_tokens:
        return True
    message = str(original or exc).lower()
    return any(token in message for token in normalized_tokens)


__all__ = ["DatabaseError", "IntegrityError", "integrity_error_has_token"]
