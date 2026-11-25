"""Storage 节点写入/统计测试（含旧库迁移回填）。"""

import sqlite3

from smart_proxy_manager import storage
from smart_proxy_manager.models import Node

from conftest import FAKE_SS_PASSWORD, FAKE_UUID


def _conn(tmp_path):
    return storage.init_db(tmp_path / "spm.db")


def _ss(name="n1", source_id=None, **kw) -> Node:
    return Node(
        name=name,
        protocol="ss",
        server="a.example.com",
        port=8388,
        source_id=source_id,
        options={"cipher": "aes-256-gcm", "password": FAKE_SS_PASSWORD},
        **kw,
    )


def test_upsert_add_then_duplicate(tmp_path):
    conn = _conn(tmp_path)
    try:
        sid = storage.add_source(conn, name="s", kind="file", location="x.yaml")
        first = storage.upsert_nodes(conn, [_ss(source_id=sid)])
        assert first == {"added": 1, "duplicates": 0}
        second = storage.upsert_nodes(conn, [_ss(source_id=sid)])
        assert second == {"added": 0, "duplicates": 1}
        assert storage.count_nodes(conn) == 1
    finally:
        conn.close()


def test_upsert_merges_sources(tmp_path):
    conn = _conn(tmp_path)
    try:
        s1 = storage.add_source(conn, name="s1", kind="file", location="a")
        s2 = storage.add_source(conn, name="s2", kind="file", location="b")
        storage.upsert_nodes(conn, [_ss(source_id=s1)])
        storage.upsert_nodes(conn, [_ss(source_id=s2)])
        nodes = storage.list_nodes(conn)
        assert len(nodes) == 1
        assert sorted(nodes[0].source_ids) == [s1, s2]
        stats = storage.node_stats(conn)
        assert stats["by_source"] == {"s1": 1, "s2": 1}
    finally:
        conn.close()


def test_list_nodes_filter_by_source_and_stats(tmp_path):
    conn = _conn(tmp_path)
    try:
        s1 = storage.add_source(conn, name="src-a", kind="file", location="a")
        s2 = storage.add_source(conn, name="src-b", kind="file", location="b")
        storage.upsert_nodes(
            conn,
            [
                _ss(source_id=s1),
                Node(
                    name="vm", protocol="vmess", server="v.example.com",
                    port=443, source_id=s2, options={"uuid": FAKE_UUID},
                ),
            ],
        )
        assert len(storage.list_nodes(conn, source_id=s1)) == 1
        assert len(storage.list_nodes(conn, source_id=s2)) == 1
        stats = storage.node_stats(conn)
        assert stats["total"] == 2
        assert stats["by_protocol"] == {"ss": 1, "vmess": 1}
        assert stats["by_source"] == {"src-a": 1, "src-b": 1}
    finally:
        conn.close()


def test_list_nodes_roundtrip_options(tmp_path):
    conn = _conn(tmp_path)
    try:
        storage.upsert_nodes(conn, [_ss()])
        node = storage.list_nodes(conn)[0]
        assert node.options["cipher"] == "aes-256-gcm"
        assert node.options["password"] == FAKE_SS_PASSWORD
        assert node.fingerprint
    finally:
        conn.close()


_LEGACY_SCHEMA = """
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL, location TEXT NOT NULL,
    is_public INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES sources(id),
    name TEXT NOT NULL, protocol TEXT NOT NULL, server TEXT NOT NULL,
    port INTEGER NOT NULL, fingerprint TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
"""


def test_migration_backfills_node_sources_for_legacy_rows(tmp_path):
    # 手工造一个「旧库」：只有 nodes.source_id，没有 node_sources 表
    db = tmp_path / "legacy.db"
    raw = sqlite3.connect(db)
    raw.executescript(_LEGACY_SCHEMA)
    raw.execute(
        "INSERT INTO sources (name, kind, location, is_public, enabled,"
        " created_at, updated_at) VALUES ('old', 'file', 'a', 0, 1, 't', 't')"
    )
    raw.execute(
        "INSERT INTO nodes (source_id, name, protocol, server, port,"
        " fingerprint, options_json, first_seen_at, last_seen_at)"
        " VALUES (1, 'legacy', 'ss', 'a.example.com', 8388, 'fp0', '{}', 't', 't')"
    )
    raw.commit()
    raw.close()

    conn = storage.init_db(db)  # 初始化时应完成回填迁移
    try:
        stats = storage.node_stats(conn)
        assert stats["by_source"] == {"old": 1}
        nodes = storage.list_nodes(conn, source_id=1)
        assert len(nodes) == 1
        assert nodes[0].name == "legacy"
    finally:
        conn.close()


def test_find_source_by_id_and_name(tmp_path):
    conn = _conn(tmp_path)
    try:
        sid = storage.add_source(conn, name="mine", kind="url", location="https://x")
        assert storage.find_source(conn, str(sid))["name"] == "mine"
        assert storage.find_source(conn, "mine")["id"] == sid
        assert storage.find_source(conn, "missing") is None
    finally:
        conn.close()
