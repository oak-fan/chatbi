"""反向代理与客户端 IP 解析工具。"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Sequence

TrustedProxyNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
_InvalidNetworkHandler = Callable[[str], None]


def parse_trusted_proxy_networks(
    values: Sequence[str],
    *,
    on_invalid: _InvalidNetworkHandler | None = None,
) -> tuple[TrustedProxyNetwork, ...]:
    """将可信代理 IP/CIDR 配置解析为网络对象。"""
    networks: list[TrustedProxyNetwork] = []
    for item in values:
        raw = item.strip()
        if not raw:
            continue
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            if on_invalid is not None:
                on_invalid(raw)
    return tuple(networks)


def is_valid_ip(value: str | None) -> bool:
    """判断字符串是否是合法 IP。"""
    return _parse_ip(value) is not None


def is_trusted_proxy(
    peer_ip: str | None,
    trusted_networks: Sequence[TrustedProxyNetwork],
) -> bool:
    """判断来源 IP 是否属于可信反向代理网段。"""
    if not peer_ip or not trusted_networks:
        return False
    parsed_ip = _parse_ip(peer_ip)
    if parsed_ip is None:
        return False
    return any(parsed_ip in network for network in trusted_networks)


def parse_forwarded_for(raw_value: str) -> list[str]:
    """解析 X-Forwarded-For，过滤非法 IP。"""
    chain: list[str] = []
    for item in raw_value.split(","):
        parsed = _parse_ip(item)
        if parsed is None:
            continue
        chain.append(str(parsed))
    return chain


def resolve_client_ip(
    *,
    peer_ip: str | None,
    forwarded_for: str | None,
    trusted_networks: Sequence[TrustedProxyNetwork],
) -> str | None:
    """结合可信代理配置解析真实客户端 IP。"""
    parsed_peer_ip = _parse_ip(peer_ip)
    normalized_peer_ip = str(parsed_peer_ip) if parsed_peer_ip is not None else None
    if forwarded_for and is_trusted_proxy(normalized_peer_ip, trusted_networks):
        chain = parse_forwarded_for(forwarded_for)
        for hop_ip in reversed(chain):
            if not is_trusted_proxy(hop_ip, trusted_networks):
                return hop_ip
        if chain:
            return chain[0]
    return normalized_peer_ip


def _parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


__all__ = [
    "TrustedProxyNetwork",
    "is_trusted_proxy",
    "is_valid_ip",
    "parse_forwarded_for",
    "parse_trusted_proxy_networks",
    "resolve_client_ip",
]
