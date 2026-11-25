"""Parser 测试：YAML / Base64 / 四种 URI / 不支持协议 / 坏数据收集。"""

import base64
import json

import pytest

from smart_proxy_manager import parser
from smart_proxy_manager.parser import ParseError

from conftest import (
    FAKE_SS_PASSWORD,
    FAKE_TROJAN_PASSWORD,
    FAKE_UUID,
    base64_subscription,
    ss_uri,
    trojan_uri,
    uri_subscription,
    vmess_uri,
    yaml_subscription,
)


# ---------------------------------------------------------------- YAML

def test_yaml_parses_supported_and_skips_unsupported():
    result = parser.parse_subscription(yaml_subscription(), source_id=3)
    assert [n.protocol for n in result.nodes] == ["ss", "vless"]
    assert result.skipped_unsupported == 1  # hysteria2
    assert result.failed == 0
    assert all(n.source_id == 3 for n in result.nodes)


def test_yaml_dangerous_top_level_keys_not_carried():
    # 生成/入库的节点只来自 proxies，顶层危险键不进入任何节点字段
    result = parser.parse_subscription(yaml_subscription())
    for node in result.nodes:
        assert "external-controller" not in node.options
        assert "script" not in node.options
    combined = str([n.options for n in result.nodes])
    assert "should-never-leak" not in combined


def test_yaml_missing_required_field_is_error_not_crash():
    text = """proxies:
  - {name: bad, type: ss, server: a.example.com, port: 8388, cipher: aes-256-gcm}
  - {name: good, type: trojan, server: b.example.com, port: 443, password: pw}
"""
    result = parser.parse_subscription(text)
    assert [n.name for n in result.nodes] == ["good"]
    assert result.failed == 1
    assert "password" in result.errors[0]


def test_yaml_bad_uuid_rejected():
    text = """proxies:
  - {name: bad, type: vmess, server: a.example.com, port: 443, uuid: not-a-uuid}
"""
    result = parser.parse_subscription(text)
    assert result.nodes == []
    assert result.failed == 1


def test_yaml_without_proxies_raises():
    with pytest.raises(ParseError):
        parser.parse_subscription("mixed-port: 7890\nrules: []\n")


# ---------------------------------------------------------------- URIs

def test_uri_subscription_mixed_batch():
    result = parser.parse_subscription(uri_subscription(), source_id=5)
    assert [n.protocol for n in result.nodes] == ["ss", "vmess", "vless", "trojan"]
    assert result.skipped_unsupported == 2  # hysteria2 + tuic
    assert result.failed == 2  # 缺密码 trojan + 垃圾行
    assert all(n.source_ids == [5] for n in result.nodes)


def test_ss_uri_fields():
    result = parser.parse_subscription(ss_uri())
    node = result.nodes[0]
    assert node.server == "ss.example.com"
    assert node.port == 8388
    assert node.options["cipher"] == "aes-256-gcm"
    assert node.options["password"] == FAKE_SS_PASSWORD
    assert node.name == "SS节点"


def test_ss_uri_legacy_whole_base64():
    inner = f"chacha20-ietf-poly1305:{FAKE_SS_PASSWORD}@legacy.example.com:8389"
    uri = "ss://" + base64.b64encode(inner.encode()).decode() + "#旧式节点"
    result = parser.parse_subscription(uri)
    assert result.failed == 0
    node = result.nodes[0]
    assert node.server == "legacy.example.com"
    assert node.options["cipher"] == "chacha20-ietf-poly1305"


def test_ss_uri_plain_userinfo():
    uri = f"ss://aes-128-gcm:{FAKE_SS_PASSWORD}@plain.example.com:8388#明文"
    result = parser.parse_subscription(uri)
    assert result.failed == 0
    assert result.nodes[0].options["cipher"] == "aes-128-gcm"


def test_vmess_uri_fields():
    result = parser.parse_subscription(vmess_uri())
    node = result.nodes[0]
    assert node.options["uuid"] == FAKE_UUID
    assert node.options["network"] == "ws"
    assert node.options["tls"] is True
    assert node.options["servername"] == "sni.example.com"
    assert node.options["ws-opts"]["path"] == "/ws"


def test_vmess_bad_uuid_error_without_leaking_uri():
    result = parser.parse_subscription(vmess_uri(uuid="not-a-uuid"))
    assert result.nodes == []
    assert result.failed == 1
    assert "vmess://" not in result.errors[0]


def test_vless_bad_uuid_rejected():
    result = parser.parse_subscription(
        "vless://not-a-uuid@vl.example.com:443?security=tls#x"
    )
    assert result.nodes == []
    assert result.failed == 1


def test_trojan_fields():
    result = parser.parse_subscription(trojan_uri())
    node = result.nodes[0]
    assert node.options["password"] == FAKE_TROJAN_PASSWORD
    assert node.options["sni"] == "tj.example.com"


def test_trojan_missing_password_rejected():
    result = parser.parse_subscription("trojan://@tj.example.com:443#x")
    assert result.nodes == []
    assert result.failed == 1


@pytest.mark.parametrize(
    "uri",
    [
        "ss://%%%bad-base64%%%@a.example.com:8388#x",
        "vless://11111111-2222-3333-4444-555555555555@a.example.com:notaport#x",
        "trojan://pw@a.example.com:99999#x",
        "vmess://!!!not-base64!!!",
    ],
)
def test_malformed_uris_are_errors_not_crashes(uri):
    result = parser.parse_subscription(uri)
    assert result.nodes == []
    assert result.failed == 1


def test_error_messages_never_echo_credentials():
    bad = "trojan://@bad.example.com:443#x\n" + trojan_uri()
    result = parser.parse_subscription(bad)
    joined = "\n".join(result.errors)
    assert FAKE_TROJAN_PASSWORD not in joined


# ---------------------------------------------------------------- Base64

def test_base64_subscription():
    result = parser.parse_subscription(base64_subscription())
    assert [n.name for n in result.nodes] == ["B64-SS", "B64-TJ"]
    assert result.failed == 0


def test_unrecognized_content_raises():
    with pytest.raises(ParseError, match="无法识别"):
        parser.parse_subscription("这是一段普通文本，不是任何订阅格式。")


def test_empty_content_raises():
    with pytest.raises(ParseError, match="为空"):
        parser.parse_subscription("   ")


def test_json_vmess_roundtrip_sample():
    # 确认 vmess 样例里的 JSON 结构与解析口径一致（防样例腐烂）
    payload = json.loads(
        base64.b64decode(vmess_uri()[len("vmess://"):]).decode("utf-8")
    )
    assert payload["add"] == "vm.example.com"
