"""Config Validator：生成配置的校验与安全写入。

校验链（任务书 5.4 / 7.2）：
1. YAML 语法与结构校验（yaml.safe_load；必须含非空 proxies，
   与 Verge 导入校验一致）；
2. 控制面键检查：出现 external-controller、secret、端口、mode 等
   由 Verge 接管的键即判不合格（本项目的生成器本就不写，校验兜底）；
3. 节点字段逐项校验：名称唯一、协议在支持集内、协议专属必填字段
   （ss 的 cipher/password、vmess/vless 的 uuid、trojan 的 password）
   完整，复用 models / parser 的校验口径；
4. 写入采用「临时文件 → 校验 → 原子替换」：任一步失败都保留上一份
   有效文件，错误报告写到输出目录（中文原因，先经脱敏，不含凭据）。

注：调用目标 Mihomo 做真实配置检查需要在 Windows 实机进行，尚未
验证，不在本模块内冒充完成。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .models import SUPPORTED_PROTOCOLS
from .redact import redact_text

# 由 Clash Verge Rev 接管的控制面键（见可行性报告 Q2），生成配置中
# 绝不允许出现。
CONTROL_PLANE_KEYS: frozenset[str] = frozenset(
    {
        "external-controller",
        "external-controller-unix",
        "external-controller-pipe",
        "external-controller-tls",
        "external-ui",
        "secret",
        "port",
        "socks-port",
        "mixed-port",
        "redir-port",
        "tproxy-port",
        "mode",
        "allow-lan",
        "bind-address",
        "log-level",
        "script",
    }
)


class ConfigValidationError(Exception):
    """配置校验不通过（中文原因，已脱敏）。"""


def _check_proxy(index: int, entry: object, problems: list[str], names: set[str]) -> None:
    label = f"第 {index} 条 proxies"
    if not isinstance(entry, dict):
        problems.append(f"{label}：条目必须是映射结构")
        return
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(f"{label}：缺少 name")
        name = ""
    elif name in names:
        problems.append(f"{label}：节点名称重复：{name}")
    names.add(name)
    protocol = str(entry.get("type") or "").strip().lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        problems.append(f"{label}（{name}）：协议不在支持集内：{protocol or '空'}")
    server = entry.get("server")
    if not isinstance(server, str) or not server.strip():
        problems.append(f"{label}（{name}）：缺少 server")
    port = entry.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        problems.append(f"{label}（{name}）：port 不合法：{port!r}")
    # 协议专属必填字段
    if protocol == "ss":
        if not str(entry.get("cipher") or "").strip():
            problems.append(f"{label}（{name}）：ss 缺少 cipher")
        if not str(entry.get("password") or ""):
            problems.append(f"{label}（{name}）：ss 缺少 password")
    elif protocol in ("vmess", "vless"):
        if not str(entry.get("uuid") or "").strip():
            problems.append(f"{label}（{name}）：{protocol} 缺少 uuid")
    elif protocol == "trojan":
        if not str(entry.get("password") or ""):
            problems.append(f"{label}（{name}）：trojan 缺少 password")


def validate_profile(yaml_text: str) -> list[str]:
    """校验一份 Mihomo YAML，返回问题列表（空列表表示通过）。"""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return [f"YAML 语法错误：{exc.__class__.__name__}"]
    if not isinstance(data, dict):
        return ["配置顶层必须是映射结构"]
    problems: list[str] = []
    leaked = sorted(k for k in data.keys() if str(k) in CONTROL_PLANE_KEYS)
    for key in leaked:
        problems.append(f"包含不允许的控制面键：{key}（该键由 Clash Verge Rev 接管）")
    proxies = data.get("proxies")
    if proxies is None:
        problems.append("缺少 proxies（Verge 导入要求含 proxies 或 proxy-providers）")
        return problems
    if not isinstance(proxies, list) or not proxies:
        problems.append("proxies 必须是非空列表（拒绝空配置）")
        return problems
    names: set[str] = set()
    for index, entry in enumerate(proxies, start=1):
        _check_proxy(index, entry, problems, names)
    return problems


def _write_error_report(report_dir: Path, target: Path, problems: list[str]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_target = re.sub(r"[^A-Za-z0-9_.-]+", "_", target.name)
    report_path = report_dir / f"validation-error-{safe_target}-{stamp}.txt"
    lines = [
        "Smart Proxy Manager 配置校验失败报告",
        f"时间（UTC）：{stamp}",
        f"目标文件：{target}",
        "结果：新配置未通过校验，原有文件保持不变（失败保旧）。",
        "问题：",
    ]
    lines.extend(f"- {redact_text(problem)}" for problem in problems)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def write_validated_profile(
    yaml_text: str,
    target: str | Path,
    *,
    report_dir: str | Path | None = None,
) -> Path:
    """校验并原子写入配置：临时文件 → 校验 → os.replace 原子替换。

    校验失败时保留目标处上一份有效文件，写错误报告并抛
    ConfigValidationError（消息含报告路径）。
    """
    target = Path(target)
    report_directory = Path(report_dir) if report_dir is not None else target.parent
    problems = validate_profile(yaml_text)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(target.name + ".tmp")
    try:
        tmp_path.write_text(yaml_text, encoding="utf-8")
        if problems:
            report_path = _write_error_report(report_directory, target, problems)
            raise ConfigValidationError(
                f"配置校验未通过，共 {len(problems)} 个问题；原文件未改动。"
                f"错误报告：{report_path}；首个问题：{redact_text(problems[0])}"
            )
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return target
