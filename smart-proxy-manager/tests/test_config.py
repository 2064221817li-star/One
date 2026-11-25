"""配置生成与校验测试：受控输出、重名处理、失败保旧、错误报告。"""

import yaml
import pytest

from smart_proxy_manager import config_gen, config_validate
from smart_proxy_manager.config_validate import (
    ConfigValidationError,
    validate_profile,
    write_validated_profile,
)
from smart_proxy_manager.models import Node

from conftest import FAKE_SS_PASSWORD, FAKE_TROJAN_PASSWORD, FAKE_UUID


def _nodes() -> list[Node]:
    return [
        Node(
            name="同名节点", protocol="ss", server="a.example.com", port=8388,
            options={"cipher": "aes-256-gcm", "password": FAKE_SS_PASSWORD},
        ),
        Node(
            name="同名节点", protocol="trojan", server="b.example.com",
            port=443, options={"password": FAKE_TROJAN_PASSWORD},
        ),
        Node(
            name="特殊:字符#节点", protocol="vmess", server="c.example.com",
            port=443, options={"uuid": FAKE_UUID, "network": "tcp"},
        ),
    ]


def test_generate_profile_structure():
    text = config_gen.generate_profile(_nodes())
    data = yaml.safe_load(text)
    assert len(data["proxies"]) == 3
    groups = data["proxy-groups"]
    assert len(groups) == 1
    assert groups[0]["type"] == "url-test"
    assert groups[0]["proxies"] == [p["name"] for p in data["proxies"]]
    assert data["rules"] == ["MATCH,自动选择"]
    assert validate_profile(text) == []


def test_generate_profile_has_no_control_plane_keys():
    data = yaml.safe_load(config_gen.generate_profile(_nodes()))
    assert not (set(data.keys()) & config_validate.CONTROL_PLANE_KEYS)
    for proxy in data["proxies"]:
        assert "external-controller" not in proxy
        assert "secret" not in proxy


def test_generate_provider_only_proxies():
    text = config_gen.generate_provider(_nodes())
    data = yaml.safe_load(text)
    assert set(data.keys()) == {"proxies"}
    assert len(data["proxies"]) == 3
    assert validate_profile(text) == []


def test_generate_name_dedup_suffixes():
    data = yaml.safe_load(config_gen.generate_provider(_nodes()))
    names = [p["name"] for p in data["proxies"]]
    assert names[0] == "同名节点"
    assert names[1] == "同名节点-2"
    assert len(set(names)) == 3


def test_generate_special_chars_roundtrip():
    text = config_gen.generate_profile(_nodes())
    data = yaml.safe_load(text)
    assert "特殊:字符#节点" in [p["name"] for p in data["proxies"]]


@pytest.mark.parametrize("generator", [config_gen.generate_profile, config_gen.generate_provider])
def test_generate_empty_nodes_rejected(generator):
    with pytest.raises(ValueError, match="为空"):
        generator([])


# ---------------------------------------------------------------- 校验

def test_validate_good_profile():
    assert validate_profile(config_gen.generate_profile(_nodes())) == []


def test_validate_rejects_control_plane_keys():
    text = "external-controller: 127.0.0.1:9090\nsecret: x\n" + config_gen.generate_provider(_nodes())
    problems = validate_profile(text)
    assert any("控制面键" in p for p in problems)


def test_validate_rejects_empty_proxies():
    assert validate_profile("proxies: []\n") != []
    assert validate_profile("proxy-groups: []\n") != []


def test_validate_rejects_bad_yaml():
    assert validate_profile("proxies: [unclosed\n") != []


def test_validate_rejects_duplicate_names_and_bad_fields():
    text = """proxies:
  - {name: dup, type: ss, server: a.example.com, port: 8388, cipher: aes-256-gcm, password: pw}
  - {name: dup, type: ss, server: a.example.com, port: 8388, cipher: aes-256-gcm, password: pw}
  - {name: bad, type: wireguard, server: a.example.com, port: 51820}
  - {name: nopw, type: trojan, server: a.example.com, port: 443}
"""
    problems = validate_profile(text)
    joined = "\n".join(problems)
    assert "重复" in joined
    assert "wireguard" in joined
    assert "password" in joined


# ------------------------------------------------------- 原子写与失败保旧

def test_write_validated_profile_success(tmp_path):
    target = tmp_path / "out" / "profile.yaml"
    result = write_validated_profile(config_gen.generate_profile(_nodes()), target)
    assert result == target
    assert target.exists()
    assert validate_profile(target.read_text(encoding="utf-8")) == []
    assert not (target.parent / (target.name + ".tmp")).exists()


def test_write_failure_keeps_old_file_and_writes_report(tmp_path):
    target = tmp_path / "profile.yaml"
    old_text = config_gen.generate_provider(_nodes())
    target.write_text(old_text, encoding="utf-8")

    bad_text = (
        "secret: topsecret\nproxies:\n"
        f"  - {{name: x, type: ss, server: a.example.com, port: 8388,"
        f" cipher: aes-256-gcm, password: {FAKE_SS_PASSWORD}}}\n"
    )
    with pytest.raises(ConfigValidationError):
        write_validated_profile(bad_text, target)
    # 旧文件原样保留
    assert target.read_text(encoding="utf-8") == old_text
    # 错误报告产生且不含凭证明文
    reports = list(tmp_path.glob("validation-error-*.txt"))
    assert len(reports) == 1
    report_text = reports[0].read_text(encoding="utf-8")
    assert "控制面键" in report_text
    assert FAKE_SS_PASSWORD not in report_text
    assert "topsecret" not in report_text
