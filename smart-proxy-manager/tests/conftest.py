"""测试共享固定样例：全部为自造假数据，不含任何真实凭据 / 真实节点。

- 密码、UUID、Token 都是显眼的 FAKE-* 假值，脱敏测试会断言它们不
  出现在任何对外输出中；
- 服务器地址使用 example.com 与 RFC 5737 文档段 192.0.2.0/24，
  不指向任何真实服务；
- 所有测试离线运行（文件样例 + httpx MockTransport）。
"""

from __future__ import annotations

import base64
import json

FAKE_SS_PASSWORD = "FAKE-SS-PASSWORD-12345"
FAKE_TROJAN_PASSWORD = "FAKE-TROJAN-PASSWORD-67890"
FAKE_UUID = "11111111-2222-3333-4444-555555555555"
FAKE_UUID_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FAKE_TOKEN = "FAKE-SUB-TOKEN-abcdef"

ALL_FAKE_SECRETS = [FAKE_SS_PASSWORD, FAKE_TROJAN_PASSWORD, FAKE_UUID, FAKE_TOKEN]


def b64encode_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def ss_uri(
    *,
    password: str = FAKE_SS_PASSWORD,
    server: str = "ss.example.com",
    port: int = 8388,
    name: str = "SS节点",
    cipher: str = "aes-256-gcm",
) -> str:
    userinfo = b64encode_text(f"{cipher}:{password}")
    return f"ss://{userinfo}@{server}:{port}#{name}"


def vmess_uri(
    *,
    uuid: str = FAKE_UUID,
    server: str = "vm.example.com",
    port: int = 443,
    name: str = "VMess节点",
) -> str:
    payload = {
        "v": "2",
        "ps": name,
        "add": server,
        "port": str(port),
        "id": uuid,
        "aid": "0",
        "scy": "auto",
        "net": "ws",
        "tls": "tls",
        "sni": "sni.example.com",
        "path": "/ws",
        "host": "cdn.example.com",
    }
    return "vmess://" + b64encode_text(json.dumps(payload))


def vless_uri(
    *,
    uuid: str = FAKE_UUID_2,
    server: str = "vl.example.com",
    port: int = 443,
    name: str = "VLESS节点",
) -> str:
    return (
        f"vless://{uuid}@{server}:{port}"
        f"?security=tls&sni=sni2.example.com&type=tcp#{name}"
    )


def trojan_uri(
    *,
    password: str = FAKE_TROJAN_PASSWORD,
    server: str = "tj.example.com",
    port: int = 443,
    name: str = "Trojan节点",
) -> str:
    return f"trojan://{password}@{server}:{port}?sni=tj.example.com#{name}"


def uri_subscription() -> str:
    """一份 URI 列表订阅：4 条有效 + 2 条不支持 + 2 条坏数据。"""
    return "\n".join(
        [
            ss_uri(),
            vmess_uri(),
            vless_uri(),
            trojan_uri(),
            "hysteria2://someone@hy.example.com:443#HY2节点",
            "tuic://someone:pass@tuic.example.com:443#TUIC节点",
            "trojan://@bad.example.com:443#缺密码节点",
            "this is not a uri",
        ]
    )


def base64_subscription() -> str:
    """Base64 编码的 URI 列表订阅（2 条有效）。"""
    return b64encode_text("\n".join([ss_uri(name="B64-SS"), trojan_uri(name="B64-TJ")]))


def yaml_subscription() -> str:
    """Mihomo YAML 订阅：含危险顶层键（应被忽略）与 1 条不支持协议。"""
    return f"""\
mixed-port: 7890
external-controller: 127.0.0.1:9090
secret: should-never-leak
script: malicious
proxies:
  - name: YAML-SS
    type: ss
    server: yaml-ss.example.com
    port: 8388
    cipher: aes-256-gcm
    password: {FAKE_SS_PASSWORD}
  - name: YAML-VLESS
    type: vless
    server: 192.0.2.20
    port: 443
    uuid: {FAKE_UUID_2}
    tls: true
    servername: yaml.example.com
  - name: YAML-HY2
    type: hysteria2
    server: hy2.example.com
    port: 443
    password: whatever
rules:
  - MATCH,DIRECT
"""
