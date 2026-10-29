"""
SEC-007 出口校验 (SSRF 防护)

HTTP/SSE 连接器的 endpoint 由租户配置, 不能被信任。默认 (严格模式) 只允许:
- https 方案
- 解析到公网可路由地址的主机

拒绝: 回环、私网、链路本地 (含云元数据 169.254.169.254)、CGNAT、多播、保留地址,
以及内嵌 IPv4 的 IPv6 形式 (IPv4-mapped / 6to4 / NAT64)。

DNS 重绑定防护: 校验发生在连接时的解析器里, 校验的就是即将连接的那个地址,
不存在"先检查、后另行解析"的窗口。重定向由调用方禁用 (见 HTTPExecutor)。

`allow_private_networks=True` 仅用于本地开发和测试, 放宽方案和地址限制。
"""

import ipaddress
import re
import socket
from urllib.parse import urlsplit

from aiohttp.abc import AbstractResolver, ResolveResult


class EgressViolation(ValueError):
    """出口校验失败。继承 ValueError, 避免被 aiohttp 当作 OSError 包装掉。"""


_NAT64 = ipaddress.ip_network("64:ff9b::/96")

# 每个标签都是十进制或 0x 十六进制数字的主机, 例如 127.1、2130706433、0x7f.0.0.1
_NUMERIC_HOST = re.compile(r"^(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*\.?$", re.IGNORECASE)


def is_blocked_address(address: str) -> bool:
    """地址不是公网可路由地址时返回 True; 无法解析时同样返回 True (fail-closed)。"""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True

    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)

    # is_global 已排除私网/回环/链路本地/CGNAT/保留段; IPv4 多播需单独排除
    return (not ip.is_global) or ip.is_multicast


def validate_endpoint(url: str, allow_private_networks: bool = False) -> None:
    """
    校验 endpoint 的方案、凭据段和字面量 IP; 不做 DNS 解析 (见 build_guarded_resolver)。

    校验失败抛出 EgressViolation。错误信息不回显完整 URL, 避免带出 URL 中的秘密。
    """
    try:
        parts = urlsplit(url)
        _ = parts.port  # 触发端口合法性检查
    except ValueError:
        raise EgressViolation("Invalid endpoint URL") from None

    scheme = (parts.scheme or "").lower()
    allowed = ("http", "https") if allow_private_networks else ("https",)
    if scheme not in allowed:
        raise EgressViolation(f"Endpoint scheme '{scheme}' is not allowed")

    host = parts.hostname
    if not host:
        raise EgressViolation("Endpoint has no host")

    if parts.username or parts.password:
        raise EgressViolation("Endpoint must not contain embedded credentials")

    if allow_private_networks:
        return

    try:
        ipaddress.ip_address(host)
    except ValueError:
        # 非规范 IP 的数字写法 (2130706433 / 127.1 / 0177.0.0.1 / 0x7f.0.0.1) 会被
        # aiohttp 当作 IP 直接连接而跳过解析器, 或被系统 inet_aton 解释为回环。
        # 无法可靠判断其含义, 一律拒绝。
        if _NUMERIC_HOST.match(host):
            raise EgressViolation("Endpoint host is an ambiguous numeric address") from None
        return  # 主机名: 在连接时由解析器校验
    if is_blocked_address(host):
        raise EgressViolation("Endpoint address is not publicly routable")


def build_guarded_resolver(
    allow_private_networks: bool = False, inner: AbstractResolver | None = None
) -> AbstractResolver:
    """
    构造 aiohttp 解析器, 解析结果中只要有一个非公网地址就整体拒绝。

    aiohttp 在函数内导入, 未安装时只影响 HTTP 传输, 不影响本模块的其余校验。
    `inner` 供测试注入。
    """
    from aiohttp.resolver import DefaultResolver

    base = inner if inner is not None else DefaultResolver()

    class GuardedResolver(AbstractResolver):
        async def resolve(
            self, host: str, port: int = 0, family: int = socket.AF_INET
        ) -> list[ResolveResult]:
            infos = await base.resolve(host, port, socket.AddressFamily(family))
            if not allow_private_networks:
                for info in infos:
                    if is_blocked_address(info["host"]):
                        raise EgressViolation(f"Host '{host}' resolves to a non-public address")
            return infos

        async def close(self) -> None:
            await base.close()

    return GuardedResolver()
