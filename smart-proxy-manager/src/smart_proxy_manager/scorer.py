"""Node Scorer：节点质量评分（阶段 2 实现，本文件先定接口）。

初始评分维度（任务书 6.2，仅为初始实验参数，必须可配置）：
- 连接成功率 45%
- 网络延迟 30%
- 历史稳定性 25%

注意事项：
- 样本不足时不能给出看似精确的分数，应标注样本量；
- 响应速度不等于安全性，评分不掺入安全判断；
- 节点最近失效、瞬时抖动等因素在阶段 2 设计时单独处理。

当前状态：骨架，阶段 2 实现。权重默认值与 config.example.toml 的
[scorer] 一致，届时从配置读取，不在代码里写死。
"""

from __future__ import annotations

DEFAULT_WEIGHTS: dict[str, float] = {
    "success_rate": 0.45,
    "latency": 0.30,
    "stability": 0.25,
}


def score_node(node_id: int, weights: dict[str, float] | None = None) -> float:
    """根据检测历史计算节点评分（计划接口，阶段 2）。"""
    raise NotImplementedError("阶段 2『智能评分』任务中实现")
