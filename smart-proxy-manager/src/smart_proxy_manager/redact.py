"""凭据脱敏：统一的敏感信息处理工具。

红线（任务书第九节）：订阅 Token、节点密码、UUID 等凭据不得出现在
日志、异常消息、错误报告与测试快照中。所有模块在把文本（尤其是 URL、
异常信息）向外输出前，都应先过本模块的脱敏函数。

策略：
- ``mask_secret``：单个凭据值只保留极少量信息（长度），不保留内容片段；
- ``redact_text``：在一整段文本中把已知的凭据值替换为 ``***``，并把
  URL 查询串中常见敏感参数（token、password、key 等）的值打码。
"""

from __future__ import annotations

import re

MASK = "***"

# URL 查询串 / 表单里常见的敏感参数名（不分大小写匹配）。
_SENSITIVE_PARAMS = (
    "token",
    "password",
    "passwd",
    "pwd",
    "uuid",
    "secret",
    "key",
    "auth",
    "access_token",
    "api_key",
    "apikey",
)

_PARAM_RE = re.compile(
    r"([?&;](?:" + "|".join(_SENSITIVE_PARAMS) + r")=)[^&\s#;]+",
    re.IGNORECASE,
)


def mask_secret(value: object) -> str:
    """把单个凭据值脱敏为不含内容的标记（仅保留长度信息）。"""
    if value is None:
        return MASK
    text = str(value)
    if not text:
        return MASK
    return f"{MASK}(len={len(text)})"


def redact_text(text: str, secrets: object = ()) -> str:
    """脱敏一段文本。

    Args:
        text: 原始文本（可能包含 URL、异常消息等）。
        secrets: 已知的凭据值集合，出现即替换为 ``***``。
    """
    result = str(text)
    for secret in secrets or ():
        if secret is None:
            continue
        value = str(secret)
        if len(value) >= 4:  # 太短的值替换意义不大且易误伤普通文本
            result = result.replace(value, MASK)
    result = _PARAM_RE.sub(r"\1" + MASK, result)
    return result
