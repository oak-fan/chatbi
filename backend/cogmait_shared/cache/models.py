"""跨服务共享的缓存领域模型。"""

from dataclasses import dataclass

RedisZSetRangeItem = str | bytes | tuple[str | bytes, float]
RedisZSetMember = str
RedisZSetScoredMember = tuple[str, float]
RedisZSetRangeResult = list[RedisZSetMember | RedisZSetScoredMember]


@dataclass(slots=True)
class CacheEntry:
    """描述通用的缓存键值对。"""

    key: str
    value: str | None
