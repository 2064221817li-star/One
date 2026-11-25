"""Deduplication Engine：节点去重。

去重指纹的输入维度（任务书 5.3）：
协议、主机、端口、传输类型、TLS 与 SNI 等连接参数，以及认证相关
参数的 **SHA-256 安全摘要**。不能只按服务器+端口去重：同一服务器、
同一端口但认证参数或 SNI 不同的，是不同的有效配置，不得误删。

指纹本身只由规范化字段与摘要拼成后再做一次 SHA-256，**不包含任何
凭据明文**，可以安全写进日志与数据库。

保留每个节点的来源记录：同一节点来自多个来源时合并 ``source_ids``，
不简单丢弃。V2RayAggregator 的合并逻辑是 O(n²) 且比较字段不全，
本实现按指纹哈希分组（O(n)），不照搬（见可行性报告第 4 节）。
"""

from __future__ import annotations

import hashlib
import json

from .models import Node


def _auth_material(node: Node) -> str:
    """提取决定连接身份的认证材料（仅用于本地计算摘要，不外传）。"""
    options = node.options
    if node.protocol == "ss":
        return f"ss|{options.get('cipher', '')}|{options.get('password', '')}"
    if node.protocol == "vmess":
        return (
            f"vmess|{str(options.get('uuid', '')).lower()}"
            f"|{options.get('alterId', 0)}|{options.get('cipher', '')}"
        )
    if node.protocol == "vless":
        return f"vless|{str(options.get('uuid', '')).lower()}|{options.get('flow', '')}"
    if node.protocol == "trojan":
        return f"trojan|{options.get('password', '')}"
    return f"{node.protocol}|"


def auth_digest(node: Node) -> str:
    """认证参数的 SHA-256 安全摘要（十六进制）。"""
    return hashlib.sha256(_auth_material(node).encode("utf-8")).hexdigest()


def fingerprint(node: Node) -> str:
    """计算节点的稳定去重指纹（SHA-256 十六进制，不含凭据明文）。"""
    options = node.options
    canonical = {
        "protocol": node.protocol,
        "server": node.server.strip().lower(),
        "port": node.port,
        "network": str(options.get("network") or "tcp").lower(),
        "tls": bool(options.get("tls")),
        "sni": str(options.get("servername") or options.get("sni") or "").lower(),
        "auth": auth_digest(node),
    }
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def deduplicate(nodes: list[Node]) -> list[Node]:
    """对节点列表去重：回填 fingerprint，合并重复节点的来源记录。

    保留首次出现的节点对象（含其名称与参数），重复项的 source_ids
    合并进来。返回去重后的列表，顺序与首次出现顺序一致。
    """
    by_fingerprint: dict[str, Node] = {}
    ordered: list[Node] = []
    for node in nodes:
        node.fingerprint = fingerprint(node)
        existing = by_fingerprint.get(node.fingerprint)
        if existing is None:
            by_fingerprint[node.fingerprint] = node
            ordered.append(node)
            continue
        for sid in node.source_ids:
            if sid not in existing.source_ids:
                existing.source_ids.append(sid)
        if existing.source_id is None and node.source_id is not None:
            existing.source_id = node.source_id
    return ordered
