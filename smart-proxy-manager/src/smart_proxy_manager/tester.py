"""Node Tester：本地节点检测（阶段 2 实现，本文件先定接口）。

原则（任务书 6.1）：
- 优先复用 Mihomo 自带健康检查 / URL Test 能力（经 REST API 调用），
  不自研测速协议；API 仅当配置了 secret 才有鉴权，未确认鉴权方式前
  不得默认对外暴露（见可行性报告 Q6）；
- 检测必须在本机网络环境执行，GitHub Actions 等外部测速结果不作数；
- 必须区分成功 / 失败 / 超时并记录失败原因，限制并发与重复频率；
- 结果写入 storage.test_results，供 scorer 计算成功率与稳定性。
  禁止编造或模拟检测结果。

当前状态：骨架，阶段 2 实现。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TestResult:
    """一次节点检测的结果（内存结构，落库走 storage）。"""

    node_id: int
    success: bool
    latency_ms: float | None = None  # 失败/超时时为 None
    error: str | None = None  # 失败原因（中文，不含凭据）


def test_node(node_id: int) -> TestResult:
    """检测单个节点的连通性与延迟（计划接口，阶段 2）。"""
    raise NotImplementedError("阶段 2『本地测速』任务中实现")
