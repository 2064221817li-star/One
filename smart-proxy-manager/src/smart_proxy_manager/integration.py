"""Integration Layer：与 Clash Verge Rev 的对接。

已验证的对接事实（阶段 0，见可行性报告 Q3/Q4）：
- Verge 本地导入是把内容**复制**进自己的配置目录，之后改原文件
  不会同步，不要假设改文件即生效；
- 可靠的更新通道：remote 型 profile 的定时拉取（Verge 的
  update_interval），或 Mihomo 的 file 型 Proxy Provider 按 interval
  重读文件（路径受 Mihomo HomeDir 安全路径限制）；
- 对接优先级（任务书 7.3）：本地文件导入 > 已验证的 Provider 更新
  方案 > 仅监听 127.0.0.1 的本地订阅服务；
- 禁止直接改 Verge 内部数据库，禁止在第一版控制系统代理。

当前状态：骨架，待阶段 1/3 对应任务实现。
"""

from __future__ import annotations

from pathlib import Path


def export_for_verge(profile_text: str, target: Path) -> Path:
    """把已校验的配置交付到与 Verge 对接的位置（计划接口）。

    交付前配置必须已通过 config_validate 校验；写入采用临时文件 +
    原子替换，失败保留旧文件。
    """
    raise NotImplementedError("阶段 1『Verge 对接』任务中实现")
