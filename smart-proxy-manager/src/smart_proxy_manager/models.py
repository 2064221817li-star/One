"""Node Normalizer 的数据基础：统一节点模型。

所有来源解析出的节点都必须先归一化为 :class:`Node` 才能入库、去重和生成
配置。模型在构造时做字段校验：协议必须在已支持集合内、服务器地址非空、
端口为 1-65535 的整数。不允许仅凭 URI 前缀判断解析成功——协议专属参数
放在 ``options`` 里，由 parser 逐项校验后填入（后续阶段细化）。

敏感参数（如密码、UUID）只允许出现在 ``options`` 中，并且：
- 不得写入普通日志（输出前必须脱敏）；
- 去重指纹只使用其安全摘要，不使用明文（见 dedup 模块）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 阶段 1 优先支持的协议（与 Mihomo 当前源码支持的出站类型核对过，
# 见 docs/feasibility-report.md Q8）。
SUPPORTED_PROTOCOLS: frozenset[str] = frozenset({"ss", "vmess", "vless", "trojan"})

# Mihomo 已支持、安排在后续批次接入解析的协议。
PLANNED_PROTOCOLS: frozenset[str] = frozenset({"hysteria2", "tuic"})


@dataclass
class Node:
    """归一化后的单个代理节点。"""

    name: str
    protocol: str  # 取值见 SUPPORTED_PROTOCOLS
    server: str
    port: int
    # 来源 id（storage.sources 表主键）；内存中临时构造时可为 None。
    source_id: int | None = None
    # 全部来源 id 列表：同一节点可由多个来源提供，去重时合并（见 dedup）。
    source_ids: list[int] = field(default_factory=list)
    # 协议专属参数：cipher、uuid、password、tls、sni、network 等。
    # parser 负责逐项校验，禁止把未校验的原始字段直接塞进来。
    options: dict[str, Any] = field(default_factory=dict)
    # 去重指纹，由 dedup 引擎生成后回填；入库前可为空字符串。
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.source_id is not None and self.source_id not in self.source_ids:
            self.source_ids.append(self.source_id)
        self.validate()

    def validate(self) -> None:
        """校验字段合法性，不合法时抛 ValueError（中文说明原因）。"""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("节点名称不能为空")
        if not isinstance(self.protocol, str):
            raise ValueError("协议类型必须是字符串")
        protocol = self.protocol.strip().lower()
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError(
                f"暂不支持的协议类型: {self.protocol!r}"
                f"（当前支持: {', '.join(sorted(SUPPORTED_PROTOCOLS))}）"
            )
        self.protocol = protocol
        if not isinstance(self.server, str) or not self.server.strip():
            raise ValueError("服务器地址不能为空")
        if any(ch.isspace() for ch in self.server):
            raise ValueError(f"服务器地址不能包含空白字符: {self.server!r}")
        # bool 是 int 的子类，必须显式排除，避免 True 被当成端口 1。
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError(f"端口必须是整数: {self.port!r}")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"端口超出范围 1-65535: {self.port}")
        if not isinstance(self.options, dict):
            raise ValueError("options 必须是字典")
