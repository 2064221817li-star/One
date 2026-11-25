"""Dedup 测试：指纹维度、来源合并、凭据不进指纹。"""

from smart_proxy_manager import dedup
from smart_proxy_manager.models import Node

from conftest import FAKE_SS_PASSWORD, FAKE_UUID


def _ss_node(**overrides) -> Node:
    base = dict(
        name="n",
        protocol="ss",
        server="a.example.com",
        port=8388,
        options={"cipher": "aes-256-gcm", "password": FAKE_SS_PASSWORD},
    )
    base.update(overrides)
    return Node(**base)


def test_same_node_same_fingerprint():
    assert dedup.fingerprint(_ss_node()) == dedup.fingerprint(_ss_node())


def test_fingerprint_contains_no_plaintext_credential():
    node = _ss_node()
    fp = dedup.fingerprint(node)
    assert FAKE_SS_PASSWORD not in fp
    assert FAKE_SS_PASSWORD not in dedup.auth_digest(node)
    assert len(fp) == 64  # SHA-256 hex


def test_same_server_different_password_not_merged():
    a = _ss_node()
    b = _ss_node(options={"cipher": "aes-256-gcm", "password": "OTHER-PW"})
    assert dedup.fingerprint(a) != dedup.fingerprint(b)
    assert len(dedup.deduplicate([a, b])) == 2


def test_same_server_different_cipher_not_merged():
    a = _ss_node()
    b = _ss_node(options={"cipher": "chacha20-ietf-poly1305", "password": FAKE_SS_PASSWORD})
    assert len(dedup.deduplicate([a, b])) == 2


def test_different_sni_not_merged():
    common = dict(protocol="trojan", server="t.example.com", port=443)
    a = Node(name="a", **common, options={"password": "pw", "sni": "one.example.com"})
    b = Node(name="b", **common, options={"password": "pw", "sni": "two.example.com"})
    assert len(dedup.deduplicate([a, b])) == 2


def test_different_network_not_merged():
    a = Node(
        name="a", protocol="vmess", server="v.example.com", port=443,
        options={"uuid": FAKE_UUID, "network": "tcp"},
    )
    b = Node(
        name="b", protocol="vmess", server="v.example.com", port=443,
        options={"uuid": FAKE_UUID, "network": "ws"},
    )
    assert len(dedup.deduplicate([a, b])) == 2


def test_exact_duplicates_merged_with_sources():
    a = _ss_node(source_id=1)
    b = _ss_node(name="另一个名字", source_id=2)
    merged = dedup.deduplicate([a, b])
    assert len(merged) == 1
    assert sorted(merged[0].source_ids) == [1, 2]
    assert merged[0].fingerprint == dedup.fingerprint(a)


def test_deduplicate_fills_fingerprint_and_keeps_order():
    # 名称不在指纹维度内：前两个节点同指纹合并，第三个端口不同独立
    nodes = [_ss_node(name="first"), _ss_node(name="same-fp"), _ss_node(port=9999)]
    result = dedup.deduplicate(nodes)
    assert len(result) == 2
    assert result[0].name == "first"  # 保留首次出现
    assert result[1].port == 9999
    assert all(n.fingerprint for n in result)
