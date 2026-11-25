"""Subscription Fetcher：订阅下载与本地文件读取。

职责：
- 按来源类型下载（HTTP/HTTPS）或读取本地订阅文件，返回原始文本；
- 安全约束（订阅内容视为不可信输入）：
  * 请求超时、响应大小上限、重定向次数上限；
  * SSRF 防护：目标主机解析到的任一 IP 若为私网 / 回环 / 链路本地 /
    保留 / 组播地址，默认拒绝；只有在调用方显式开启 ``allow_private``
    （对应用户在配置中允许私人局域网订阅）时才放行。本机文件来源与
    每次重定向的目标都执行同样的检查；
  * 下载失败区分超时、HTTP 错误、空响应等原因，用中文异常信息向上
    报告，绝不静默返回空内容冒充成功；
  * 异常信息中的 URL 先脱敏（查询串里的 token 等参数打码），
    见 redact 模块。

已知局限：SSRF 检查在请求前做 DNS 解析，无法完全防御 DNS rebinding
（校验后解析结果被替换）；个人本地工具场景下接受该残余风险，真正的
高风险场景应再配合出口防火墙。
"""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .redact import redact_text

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 单个订阅响应大小上限
DEFAULT_MAX_REDIRECTS = 5

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class FetchError(Exception):
    """订阅获取失败（中文原因，不含凭据明文）。"""


def _ip_is_blocked(ip_text: str) -> bool:
    """判断一个 IP 是否属于默认禁止访问的非公网范围。"""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True  # 解析不出的地址一律按危险处理
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _default_resolver(host: str) -> list[str]:
    """默认主机解析器：返回该主机的全部 A/AAAA 地址文本。"""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def _check_url_allowed(
    url: str,
    *,
    allow_private: bool,
    resolver,
) -> None:
    """校验 URL 的协议与目标地址，危险时抛 FetchError。"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"订阅地址只支持 http/https：{redact_text(url)}")
    host = parts.hostname
    if not host:
        raise FetchError(f"订阅地址缺少主机名：{redact_text(url)}")
    if allow_private:
        return
    # IP 字面量直接判断，域名则解析后逐个判断。
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        try:
            addresses = resolver(host)
        except Exception:
            raise FetchError(f"无法解析订阅主机地址：{host}") from None
        if not addresses:
            raise FetchError(f"无法解析订阅主机地址：{host}")
    for address in addresses:
        if _ip_is_blocked(address):
            raise FetchError(
                f"拒绝访问非公网地址 {address}（主机 {host}）：默认禁止订阅"
                "指向私网/回环地址；确为自有局域网订阅时，请在确认安全后"
                "显式开启允许私网地址选项"
            )


def _fetch_file(location: str, *, max_bytes: int) -> str:
    path = Path(location).expanduser()
    if not path.is_file():
        raise FetchError(f"本地订阅文件不存在：{location}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FetchError(f"读取本地订阅文件失败：{location}（{exc.strerror or exc}）") from None
    if len(raw) > max_bytes:
        raise FetchError(
            f"本地订阅文件过大：{len(raw)} 字节，超过上限 {max_bytes} 字节"
        )
    return _decode(raw, origin=f"本地文件 {location}")


def _decode(raw: bytes, *, origin: str) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FetchError(f"订阅内容不是有效的 UTF-8 文本（来源：{origin}）") from None
    if not text.strip():
        raise FetchError(f"订阅内容为空（来源：{origin}）")
    return text


def _fetch_url(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    max_redirects: int,
    allow_private: bool,
    resolver,
    transport: httpx.BaseTransport | None,
) -> str:
    current = url
    timeout_cfg = httpx.Timeout(timeout)
    with httpx.Client(
        timeout=timeout_cfg,
        follow_redirects=False,
        transport=transport,
        headers={"User-Agent": "SmartProxyManager/0.1"},
    ) as client:
        for hop in range(max_redirects + 1):
            _check_url_allowed(current, allow_private=allow_private, resolver=resolver)
            try:
                with client.stream("GET", current) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError(
                                f"订阅地址返回重定向但缺少目标（HTTP {response.status_code}）"
                            )
                        if hop >= max_redirects:
                            raise FetchError(
                                f"订阅地址重定向次数超过上限 {max_redirects} 次"
                            )
                        from urllib.parse import urljoin

                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise FetchError(
                            f"下载订阅失败：HTTP {response.status_code}"
                            f"（地址：{redact_text(url)}）"
                        )
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError(
                                f"订阅响应过大：超过上限 {max_bytes} 字节，已中断下载"
                            )
                        chunks.append(chunk)
                    return _decode(b"".join(chunks), origin=f"地址 {redact_text(url)}")
            except FetchError:
                raise
            except httpx.TimeoutException:
                raise FetchError(
                    f"下载订阅超时（{timeout} 秒）：{redact_text(url)}"
                ) from None
            except httpx.HTTPError as exc:
                raise FetchError(
                    f"下载订阅失败：{redact_text(str(exc))}（地址：{redact_text(url)}）"
                ) from None
    raise FetchError(f"订阅地址重定向次数超过上限 {max_redirects} 次")


def fetch_source(
    location: str,
    kind: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_private: bool = False,
    resolver=None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """获取一个来源的原始订阅文本。

    Args:
        location: 订阅 URL 或本地文件路径。
        kind: 'url' 或 'file'。
        allow_private: 是否允许 URL 指向私网/回环地址（默认否）。
        resolver: 主机解析函数 ``(host) -> [ip, ...]``，测试可注入；
            默认用系统 DNS。
        transport: httpx 传输层，测试可注入 MockTransport。

    Returns:
        订阅原始文本。失败时抛 FetchError 并说明原因，不返回空字符串
        冒充成功。
    """
    if kind == "file":
        return _fetch_file(location, max_bytes=max_bytes)
    if kind == "url":
        return _fetch_url(
            location,
            timeout=timeout,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            allow_private=allow_private,
            resolver=resolver or _default_resolver,
            transport=transport,
        )
    raise FetchError(f"未知来源类型：{kind!r}（应为 'url' 或 'file'）")
