"""SQLite 存储初始化测试（临时目录建库，不访问网络）。"""

import sqlite3

import pytest

from smart_proxy_manager import storage


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row["name"] for row in rows}


def test_init_db_creates_tables(tmp_path):
    conn = storage.init_db(tmp_path / "spm.db")
    try:
        assert {"sources", "nodes", "test_results"} <= _table_names(conn)
    finally:
        conn.close()


def test_init_db_creates_parent_dirs(tmp_path):
    db = tmp_path / "nested" / "dir" / "spm.db"
    conn = storage.init_db(db)
    try:
        assert db.exists()
    finally:
        conn.close()


def test_reinit_preserves_data(tmp_path):
    db = tmp_path / "spm.db"
    conn = storage.init_db(db)
    storage.add_source(
        conn, name="s1", kind="url", location="https://example.com/sub"
    )
    conn.close()

    # 重复初始化不得清掉已有数据
    conn2 = storage.init_db(db)
    try:
        sources = storage.list_sources(conn2)
        assert len(sources) == 1
        assert sources[0]["name"] == "s1"
        assert sources[0]["is_public"] == 0
    finally:
        conn2.close()


def test_add_and_list_source_public_flag(tmp_path):
    conn = storage.init_db(tmp_path / "spm.db")
    try:
        new_id = storage.add_source(
            conn,
            name="pub",
            kind="file",
            location="D:/subs/public.yaml",
            is_public=True,
        )
        assert new_id == 1
        sources = storage.list_sources(conn)
        assert sources[0]["is_public"] == 1
        assert sources[0]["enabled"] == 1
    finally:
        conn.close()


def test_add_source_bad_kind_rejected(tmp_path):
    conn = storage.init_db(tmp_path / "spm.db")
    try:
        with pytest.raises(ValueError):
            storage.add_source(conn, name="x", kind="ftp", location="ftp://x")
    finally:
        conn.close()


def test_add_source_duplicate_name_rejected(tmp_path):
    conn = storage.init_db(tmp_path / "spm.db")
    try:
        storage.add_source(conn, name="dup", kind="url", location="https://a")
        with pytest.raises(sqlite3.IntegrityError):
            storage.add_source(conn, name="dup", kind="url", location="https://b")
    finally:
        conn.close()


def test_count_nodes_empty(tmp_path):
    conn = storage.init_db(tmp_path / "spm.db")
    try:
        assert storage.count_nodes(conn) == 0
    finally:
        conn.close()
