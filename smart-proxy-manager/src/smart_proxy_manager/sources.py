"""Source Manager：订阅来源的定义与管理。

职责：
- 校验来源定义（类型 url/file、地址格式、公私隔离标记）；
- 增删改查的业务规则（实际落库走 storage 模块）；
- 公开来源（如 V2RayAggregator 已生成的公开订阅）与私人订阅严格隔离：
  隔离标记在来源层确定，后续解析、筛选、生成配置都不得跨界混用。

当前状态：骨架。来源的存储读写已在 storage.add_source / list_sources
实现；本模块的业务校验函数待阶段 1「来源管理」任务实现。
"""

from __future__ import annotations

SOURCE_KINDS: tuple[str, ...] = ("url", "file")


def validate_source_definition(definition: dict) -> dict:
    """校验一份来源定义并返回规范化结果（计划接口）。

    计划校验项：name 非空且不重复、kind ∈ SOURCE_KINDS、location 格式
    合法、is_public 显式给出（不允许默认把私人订阅当公开源）。
    """
    raise NotImplementedError("阶段 1『来源管理』任务中实现")
