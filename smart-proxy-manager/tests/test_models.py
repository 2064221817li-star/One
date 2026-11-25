"""Node 统一模型的字段校验测试（固定样例，不访问网络）。"""

import pytest

from smart_proxy_manager.models import Node


def test_valid_node_minimal():
    node = Node(name="节点A", protocol="ss", server="example.com", port=8388)
    assert node.protocol == "ss"
    assert node.options == {}
    assert node.fingerprint == ""


def test_valid_node_full_options():
    node = Node(
        name="节点B",
        protocol="VMess",  # 大小写应被规范化
        server="192.0.2.10",
        port=443,
        source_id=1,
        options={"uuid": "00000000-0000-0000-0000-000000000000", "tls": True},
    )
    assert node.protocol == "vmess"
    assert node.options["tls"] is True


@pytest.mark.parametrize("bad_name", ["", "   ", None, 123])
def test_empty_or_bad_name_rejected(bad_name):
    with pytest.raises(ValueError):
        Node(name=bad_name, protocol="ss", server="example.com", port=8388)


@pytest.mark.parametrize("bad_protocol", ["", "socks5", "hysteria2", None])
def test_unsupported_protocol_rejected(bad_protocol):
    # hysteria2 在 Mihomo 中受支持，但本项目阶段 1 尚未接入解析，应明确拒绝
    with pytest.raises(ValueError):
        Node(name="n", protocol=bad_protocol, server="example.com", port=8388)


@pytest.mark.parametrize("bad_server", ["", "  ", "exa mple.com", None])
def test_bad_server_rejected(bad_server):
    with pytest.raises(ValueError):
        Node(name="n", protocol="ss", server=bad_server, port=8388)


@pytest.mark.parametrize("bad_port", [0, 65536, -1, "8388", 8388.5, True, None])
def test_bad_port_rejected(bad_port):
    with pytest.raises(ValueError):
        Node(name="n", protocol="ss", server="example.com", port=bad_port)


@pytest.mark.parametrize("ok_port", [1, 443, 65535])
def test_boundary_ports_accepted(ok_port):
    node = Node(name="n", protocol="trojan", server="example.com", port=ok_port)
    assert node.port == ok_port


def test_bad_options_rejected():
    with pytest.raises(ValueError):
        Node(name="n", protocol="ss", server="example.com", port=8388, options="x")
