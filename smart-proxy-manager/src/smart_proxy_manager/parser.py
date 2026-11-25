"""Protocol Parser：把订阅原始文本解析为统一 Node 模型。

支持的输入格式：
- Mihomo/Clash YAML（含 proxies 列表，只用 yaml.safe_load；只取 proxies，
  其余顶层键——包括脚本、external-controller、规则等——一律不透传）；
- Base64 编码的 URI 列表订阅；
- 单条/多条分享链接：ss:// / vmess:// / vless:// / trojan://
  （hysteria2:// / tuic:// 等暂不支持的协议跳过并计数，不中断整批）。

校验要求（硬性）：不允许仅凭 URI 前缀判定解析成功——每种协议都逐项
校验必要字段（主机、端口、加密方式 / UUID / 密码及其格式），缺字段或
格式不合法的条目记入错误列表并丢弃，不能带病入库。

错误收集：单条失败不影响整批；错误信息只写行号与原因，**绝不回显
原始 URI**（其中含密码 / UUID 明文）。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid as uuid_module
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

from .models import PLANNED_PROTOCOLS, SUPPORTED_PROTOCOLS, Node

_URI_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://")

# URI scheme -> 归一化协议名（hy2 是 hysteria2 的常见别名）。
_SCHEME_TO_PROTOCOL = {
    "ss": "ss",
    "vmess": "vmess",
    "vless": "vless",
    "trojan": "trojan",
    "hy2": "hysteria2",
}


@dataclass
class ParseResult:
    """一份订阅的解析结果汇总。"""

    nodes: list[Node] = field(default_factory=list)
    skipped_unsupported: int = 0  # 因协议暂不支持而跳过的条目数
    errors: list[str] = field(default_factory=list)  # 逐条失败原因（不含明文凭据）

    @property
    def failed(self) -> int:
        return len(self.errors)


class ParseError(Exception):
    """整份订阅无法识别格式等整体性失败（中文原因）。"""


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def _b64decode_text(data: str) -> bytes:
    """宽松 Base64 解码：补齐填充、容忍 URL-safe 字符与空白。"""
    cleaned = re.sub(r"\s+", "", data)
    cleaned = cleaned.replace("-", "+").replace("_", "/")
    cleaned += "=" * (-len(cleaned) % 4)
    return base64.b64decode(cleaned, validate=True)


def _valid_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid_module.UUID(value.strip())
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _coerce_port(value: object) -> int:
    """把端口值转为 int 并做范围校验，失败抛 ValueError。"""
    if isinstance(value, bool):
        raise ValueError("端口不合法")
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"端口不合法：{value!r}") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"端口超出范围 1-65535：{port}")
    return port


def _fallback_name(protocol: str, server: str, port: int) -> str:
    return f"{protocol}-{server}-{port}"


# ----------------------------------------------------------------------
# YAML（Mihomo/Clash）解析
# ----------------------------------------------------------------------

# 从 YAML proxies 条目中保留的字段（其余字段不透传，防止不可信字段
# 被带进生成配置；name/type/server/port 单独处理）。
_YAML_KEEP_FIELDS = {
    "cipher",
    "password",
    "uuid",
    "alterId",
    "udp",
    "tls",
    "skip-cert-verify",
    "servername",
    "sni",
    "alpn",
    "network",
    "ws-opts",
    "grpc-opts",
    "reality-opts",
    "flow",
    "client-fingerprint",
    "plugin",
    "plugin-opts",
    "obfs",
    "obfs-password",
    "protocol",
    "protocol-param",
}


def _node_from_yaml_proxy(entry: object) -> Node:
    """把一条 YAML proxies 记录转成 Node，逐字段校验。"""
    if not isinstance(entry, dict):
        raise ValueError("proxies 条目必须是映射结构")
    protocol = str(entry.get("type") or "").strip().lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise _UnsupportedProtocol(protocol or "?")
    name = str(entry.get("name") or "").strip()
    server = str(entry.get("server") or "").strip()
    if not server:
        raise ValueError("缺少 server 字段")
    port = _coerce_port(entry.get("port"))
    options = {
        key: value
        for key, value in entry.items()
        if key in _YAML_KEEP_FIELDS and value is not None
    }
    _validate_protocol_fields(protocol, options)
    return Node(
        name=name or _fallback_name(protocol, server, port),
        protocol=protocol,
        server=server,
        port=port,
        options=options,
    )


class _UnsupportedProtocol(Exception):
    def __init__(self, protocol: str) -> None:
        super().__init__(protocol)
        self.protocol = protocol


def _validate_protocol_fields(protocol: str, options: dict) -> None:
    """校验协议专属必填字段（YAML 与 URI 两条路径共用）。"""
    if protocol == "ss":
        if not str(options.get("cipher") or "").strip():
            raise ValueError("ss 节点缺少 cipher（加密方式）")
        if not str(options.get("password") or ""):
            raise ValueError("ss 节点缺少 password")
    elif protocol == "vmess":
        if not _valid_uuid(options.get("uuid")):
            raise ValueError("vmess 节点 uuid 缺失或格式不正确")
    elif protocol == "vless":
        if not _valid_uuid(options.get("uuid")):
            raise ValueError("vless 节点 uuid 缺失或格式不正确")
    elif protocol == "trojan":
        if not str(options.get("password") or ""):
            raise ValueError("trojan 节点缺少 password")


def _parse_yaml(content: str, result: ParseResult, source_id: int | None) -> None:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ParseError(f"YAML 解析失败：{exc.__class__.__name__}") from None
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise ParseError("YAML 订阅中未找到 proxies 列表")
    # 只取 proxies：脚本、external-controller、rules 等顶层键全部丢弃，
    # 不透传到后续任何环节。
    for index, entry in enumerate(data["proxies"], start=1):
        try:
            node = _node_from_yaml_proxy(entry)
        except _UnsupportedProtocol:
            # 与 URI 路径口径一致：只计数，不计入逐条失败
            result.skipped_unsupported += 1
            continue
        except ValueError as exc:
            result.errors.append(f"第 {index} 条 proxies：{exc}")
            continue
        node.source_id = source_id
        if source_id is not None and source_id not in node.source_ids:
            node.source_ids.append(source_id)
        result.nodes.append(node)


# ----------------------------------------------------------------------
# URI 解析
# ----------------------------------------------------------------------

def _parse_ss(uri: str) -> Node:
    """解析 ss:// 链接（SIP002 与旧式整体 Base64 两种形态）。"""
    rest = uri[len("ss://"):]
    name = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
        name = unquote(fragment).strip()
    plugin = None
    if "?" in rest:
        rest, query = rest.split("?", 1)
        plugin = parse_qs(query).get("plugin", [None])[0]

    if "@" in rest:
        userinfo, hostport = rest.rsplit("@", 1)
        # userinfo 可能是 base64(method:password) 或明文 method:password
        try:
            decoded = _b64decode_text(userinfo).decode("utf-8")
            if ":" in decoded:
                userinfo = decoded
        except (binascii.Error, UnicodeDecodeError, ValueError):
            userinfo = unquote(userinfo)
        if ":" not in userinfo:
            raise ValueError("ss 链接缺少加密方式或密码")
        method, password = userinfo.split(":", 1)
        method, password = method.strip(), password
    else:
        # 旧式：整体 base64(method:password@host:port)
        try:
            decoded = _b64decode_text(rest).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise ValueError("ss 链接 Base64 解码失败") from None
        if "@" not in decoded:
            raise ValueError("ss 链接格式不正确（缺少 @）")
        userinfo, hostport = decoded.rsplit("@", 1)
        if ":" not in userinfo:
            raise ValueError("ss 链接缺少加密方式或密码")
        method, password = userinfo.split(":", 1)
        method, password = method.strip(), password

    host, sep, port_text = hostport.rpartition(":")
    if not sep or not host.strip():
        raise ValueError("ss 链接缺少主机或端口")
    port = _coerce_port(port_text)
    options: dict = {"cipher": method, "password": password}
    if plugin:
        options["plugin"] = plugin
    _validate_protocol_fields("ss", options)
    host = host.strip().strip("[]")
    return Node(
        name=name or _fallback_name("ss", host, port),
        protocol="ss",
        server=host,
        port=port,
        options=options,
    )


def _parse_vmess(uri: str) -> Node:
    """解析 vmess:// 链接（Base64 编码的 JSON）。"""
    payload = uri[len("vmess://"):].split("#", 1)[0]
    try:
        data = json.loads(_b64decode_text(payload).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise ValueError("vmess 链接 Base64/JSON 解码失败") from None
    if not isinstance(data, dict):
        raise ValueError("vmess 链接内容不是 JSON 对象")
    server = str(data.get("add") or "").strip()
    if not server:
        raise ValueError("vmess 链接缺少服务器地址（add）")
    port = _coerce_port(data.get("port"))
    options: dict = {
        "uuid": str(data.get("id") or "").strip(),
        "alterId": 0,
        "cipher": str(data.get("scy") or "auto").strip() or "auto",
        "network": str(data.get("net") or "tcp").strip() or "tcp",
        "tls": str(data.get("tls") or "").strip().lower() == "tls",
    }
    try:
        options["alterId"] = int(data.get("aid") or 0)
    except (TypeError, ValueError):
        raise ValueError("vmess 链接 alterId（aid）不合法") from None
    sni = str(data.get("sni") or "").strip()
    if sni:
        options["servername"] = sni
    if options["network"] == "ws":
        ws_opts: dict = {}
        path = str(data.get("path") or "").strip()
        if path:
            ws_opts["path"] = path
        host = str(data.get("host") or "").strip()
        if host:
            ws_opts["headers"] = {"Host": host}
        if ws_opts:
            options["ws-opts"] = ws_opts
    _validate_protocol_fields("vmess", options)
    name = str(data.get("ps") or "").strip()
    return Node(
        name=name or _fallback_name("vmess", server, port),
        protocol="vmess",
        server=server,
        port=port,
        options=options,
    )


def _split_host_port(netloc: str) -> tuple[str, int]:
    host, sep, port_text = netloc.rpartition(":")
    if not sep or not host.strip():
        raise ValueError("链接缺少主机或端口")
    return host.strip().strip("[]"), _coerce_port(port_text)


def _parse_vless(uri: str) -> Node:
    """解析 vless:// 链接。"""
    parts = urlsplit(uri)
    userinfo = unquote(parts.username or "")
    if not _valid_uuid(userinfo):
        raise ValueError("vless 链接 uuid 缺失或格式不正确")
    host, port = _split_host_port(parts.netloc.rsplit("@", 1)[-1])
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    security = (query.get("security") or "").strip().lower()
    options: dict = {
        "uuid": userinfo,
        "network": (query.get("type") or "tcp").strip() or "tcp",
        "tls": security in ("tls", "reality"),
    }
    if security == "reality":
        reality_opts: dict = {}
        if query.get("pbk"):
            reality_opts["public-key"] = query["pbk"]
        if query.get("sid"):
            reality_opts["short-id"] = query["sid"]
        if reality_opts:
            options["reality-opts"] = reality_opts
    sni = (query.get("sni") or "").strip()
    if sni:
        options["servername"] = sni
    flow = (query.get("flow") or "").strip()
    if flow:
        options["flow"] = flow
    fingerprint = (query.get("fp") or "").strip()
    if fingerprint:
        options["client-fingerprint"] = fingerprint
    if options["network"] == "ws":
        ws_opts: dict = {}
        if query.get("path"):
            ws_opts["path"] = query["path"]
        if query.get("host"):
            ws_opts["headers"] = {"Host": query["host"]}
        if ws_opts:
            options["ws-opts"] = ws_opts
    _validate_protocol_fields("vless", options)
    name = unquote(parts.fragment or "").strip()
    return Node(
        name=name or _fallback_name("vless", host, port),
        protocol="vless",
        server=host,
        port=port,
        options=options,
    )


def _parse_trojan(uri: str) -> Node:
    """解析 trojan:// 链接。"""
    parts = urlsplit(uri)
    password = unquote(parts.username or "")
    if parts.password:  # 罕见形态 user:password@
        password = f"{password}:{unquote(parts.password)}"
    if not password:
        raise ValueError("trojan 链接缺少密码")
    host, port = _split_host_port(parts.netloc.rsplit("@", 1)[-1])
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    options: dict = {"password": password}
    network = (query.get("type") or "").strip()
    if network:
        options["network"] = network
    sni = (query.get("sni") or query.get("peer") or "").strip()
    if sni:
        options["sni"] = sni
    if (query.get("allowInsecure") or "").strip() in ("1", "true"):
        options["skip-cert-verify"] = True
    _validate_protocol_fields("trojan", options)
    name = unquote(parts.fragment or "").strip()
    return Node(
        name=name or _fallback_name("trojan", host, port),
        protocol="trojan",
        server=host,
        port=port,
        options=options,
    )


_URI_PARSERS = {
    "ss": _parse_ss,
    "vmess": _parse_vmess,
    "vless": _parse_vless,
    "trojan": _parse_trojan,
}


def _parse_uri_lines(text: str, result: ParseResult, source_id: int | None) -> None:
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        match = _URI_SCHEME_RE.match(line)
        if not match:
            result.errors.append(f"第 {lineno} 行：不是可识别的分享链接")
            continue
        scheme = match.group(1).lower()
        protocol = _SCHEME_TO_PROTOCOL.get(scheme, scheme)
        if protocol in PLANNED_PROTOCOLS or protocol not in SUPPORTED_PROTOCOLS:
            result.skipped_unsupported += 1
            continue
        parser = _URI_PARSERS[protocol]
        try:
            node = parser(line)
        except ValueError as exc:
            # 注意：错误信息只含行号与原因，不回显原始链接（防凭据泄漏）
            result.errors.append(f"第 {lineno} 行：{exc}")
            continue
        node.source_id = source_id
        if source_id is not None and source_id not in node.source_ids:
            node.source_ids.append(source_id)
        result.nodes.append(node)


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

def parse_subscription(
    content: str, *, source_id: int | None = None
) -> ParseResult:
    """解析一份订阅文本，返回 ParseResult（节点 + 跳过数 + 逐条错误）。

    格式自动识别：含分享链接行 → URI 列表；YAML 且含 proxies → YAML；
    整体 Base64 → 解码后按 URI 列表处理。整份无法识别时抛 ParseError。
    """
    if content is None or not str(content).strip():
        raise ParseError("订阅内容为空")
    text = str(content).strip().lstrip("\ufeff")
    result = ParseResult()

    has_uri_line = any(
        _URI_SCHEME_RE.match(line.strip()) for line in text.splitlines() if line.strip()
    )
    if has_uri_line:
        _parse_uri_lines(text, result, source_id)
        return result

    # 试 YAML（含 proxies 才算 YAML 订阅）
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("proxies"), list):
        _parse_yaml(text, result, source_id)
        return result

    # 试整体 Base64 编码的 URI 列表
    try:
        decoded = _b64decode_text(text).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        decoded = ""
    if decoded and "://" in decoded:
        _parse_uri_lines(decoded, result, source_id)
        return result

    raise ParseError("无法识别订阅格式（不是 YAML、URI 列表或 Base64 订阅）")
