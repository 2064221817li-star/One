"""Config Generator：生成 Mihomo 兼容配置。

生成规则（已由阶段 0 源码验证，见可行性报告 Q1/Q2）：
- Verge 导入校验只要求 YAML 含 ``proxies`` 或 ``proxy-providers`` 之一；
- 两种受控输出：
  (A) 完整 profile：proxies + 一个 url-test 代理组 + 极简兜底 rules，
      可作为独立 profile 导入 Verge 使用；
  (B) provider 数据文件：仅 proxies 列表，供用户现有 profile 用
      file 型 proxy-provider 引用，不触碰其现有规则；
- **禁止**写入 external-controller、secret、端口、mode 等控制面键
  （由 Verge 接管）；输出内容完全由本模块按 Node 模型构造，不复制
  订阅自带的任何顶层内容；
- 节点重名自动加后缀（-2、-3…）保证唯一；YAML 用 PyYAML safe_dump
  输出，特殊字符自动正确引用。
"""

from __future__ import annotations

import yaml

from .models import Node

GROUP_NAME = "自动选择"
DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"
DEFAULT_TEST_INTERVAL = 300


def node_to_proxy(node: Node, *, name: str | None = None) -> dict:
    """把一个 Node 转成 Mihomo proxies 条目（字段来自已校验的 options）。"""
    proxy: dict = {
        "name": name if name is not None else node.name,
        "type": node.protocol,
        "server": node.server,
        "port": node.port,
    }
    for key, value in node.options.items():
        if key not in proxy:
            proxy[key] = value
    return proxy


def _unique_names(nodes: list[Node]) -> list[str]:
    """为节点生成互不重复的输出名称（重名加 -2、-3 后缀）。"""
    seen: dict[str, int] = {}
    names: list[str] = []
    for node in nodes:
        base = node.name
        count = seen.get(base, 0) + 1
        seen[base] = count
        names.append(base if count == 1 else f"{base}-{count}")
    return names


def _proxies_with_unique_names(nodes: list[Node]) -> tuple[list[dict], list[str]]:
    names = _unique_names(nodes)
    proxies = [node_to_proxy(node, name=name) for node, name in zip(nodes, names)]
    return proxies, names


def _require_nodes(nodes: list[Node]) -> None:
    if not nodes:
        raise ValueError("节点列表为空，拒绝生成空配置覆盖已有文件（失败保旧）")


def generate_profile(
    nodes: list[Node],
    *,
    group_name: str = GROUP_NAME,
    test_url: str = DEFAULT_TEST_URL,
    test_interval: int = DEFAULT_TEST_INTERVAL,
) -> str:
    """生成完整 profile（方案 A）：proxies + url-test 组 + 兜底 rules。"""
    _require_nodes(nodes)
    proxies, names = _proxies_with_unique_names(nodes)
    config = {
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": group_name,
                "type": "url-test",
                "proxies": names,
                "url": test_url,
                "interval": test_interval,
            }
        ],
        "rules": [f"MATCH,{group_name}"],
    }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def generate_provider(nodes: list[Node]) -> str:
    """生成 provider 数据文件（方案 B）：仅 proxies 列表。"""
    _require_nodes(nodes)
    proxies, _ = _proxies_with_unique_names(nodes)
    return yaml.safe_dump(
        {"proxies": proxies}, allow_unicode=True, sort_keys=False
    )
