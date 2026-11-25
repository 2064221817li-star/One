"""Storage Manager：SQLite 本地存储。

负责数据库初始化与最基础的读写。表结构：
- ``sources``：订阅来源（元数据；注意订阅 URL 可能含 Token，
  读取展示时应脱敏，不要把完整 URL 写进日志）；
- ``nodes``：归一化后的节点，``options_json`` 存协议专属参数（含敏感
  参数），只存本地库文件，不进 Git、不进普通日志；
- ``node_sources``：节点与来源的多对多关联（同一节点可来自多个来源，
  旧库由 ``_migrate`` 从 nodes.source_id 回填）；
- ``test_results``：节点检测历史（阶段 2 写入）。

初始化可重复执行（``CREATE TABLE IF NOT EXISTS``），不会清掉已有数据。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL CHECK (kind IN ('url', 'file')),
    location    TEXT NOT NULL,
    is_public   INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     INTEGER REFERENCES sources(id),
    name          TEXT NOT NULL,
    protocol      TEXT NOT NULL,
    server        TEXT NOT NULL,
    port          INTEGER NOT NULL,
    fingerprint   TEXT NOT NULL DEFAULT '',
    options_json  TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_fingerprint ON nodes(fingerprint);
CREATE INDEX IF NOT EXISTS idx_nodes_source ON nodes(source_id);

CREATE TABLE IF NOT EXISTS node_sources (
    node_id   INTEGER NOT NULL REFERENCES nodes(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    PRIMARY KEY (node_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_node_sources_source ON node_sources(source_id);

CREATE TABLE IF NOT EXISTS test_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    INTEGER NOT NULL REFERENCES nodes(id),
    tested_at  TEXT NOT NULL,
    success    INTEGER NOT NULL,
    latency_ms REAL,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_test_results_node ON test_results(node_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """打开（必要时创建）数据库并确保表结构存在，返回连接。

    可重复调用：已有数据不会被清除。
    """
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """兼容迁移：为旧库补齐 node_sources 的历史数据。

    旧版本 nodes 表只有单个 source_id；把它回填进 node_sources，
    使按来源统计在新旧库上结果一致。全部语句幂等，可重复执行。
    """
    conn.execute(
        "INSERT OR IGNORE INTO node_sources (node_id, source_id)"
        " SELECT id, source_id FROM nodes WHERE source_id IS NOT NULL"
    )


def add_source(
    conn: sqlite3.Connection,
    *,
    name: str,
    kind: str,
    location: str,
    is_public: bool = False,
) -> int:
    """新增一个订阅来源，返回其 id。name 重复时抛 sqlite3.IntegrityError。"""
    if kind not in ("url", "file"):
        raise ValueError(f"来源类型必须是 'url' 或 'file': {kind!r}")
    if not name.strip() or not location.strip():
        raise ValueError("来源名称和地址不能为空")
    now = _now()
    cur = conn.execute(
        "INSERT INTO sources (name, kind, location, is_public, enabled,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
        (name.strip(), kind, location.strip(), int(is_public), now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_sources(conn: sqlite3.Connection) -> list[dict]:
    """列出全部来源（按 id 升序）。返回字典列表，便于服务层/CLI 展示。"""
    rows = conn.execute(
        "SELECT id, name, kind, location, is_public, enabled, created_at,"
        " updated_at FROM sources ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


def count_nodes(conn: sqlite3.Connection) -> int:
    """当前库中节点总数（供统计命令使用）。"""
    row = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()
    return int(row["c"])


def node_options(node_id: int, conn: sqlite3.Connection) -> dict:
    """读取某节点的 options（占位辅助，供后续模块使用）。"""
    row = conn.execute(
        "SELECT options_json FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"节点不存在: id={node_id}")
    return json.loads(row["options_json"])


# ----------------------------------------------------------------------
# 来源查询
# ----------------------------------------------------------------------

_SOURCE_COLUMNS = (
    "id, name, kind, location, is_public, enabled, created_at, updated_at"
)


def get_source(conn: sqlite3.Connection, source_id: int) -> dict | None:
    """按 id 查来源，不存在返回 None。"""
    row = conn.execute(
        f"SELECT {_SOURCE_COLUMNS} FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def find_source(conn: sqlite3.Connection, identifier: str) -> dict | None:
    """按 id 或名称查来源（CLI 用：纯数字先按 id，否则按名称）。"""
    text = str(identifier).strip()
    if text.isdigit():
        found = get_source(conn, int(text))
        if found is not None:
            return found
    row = conn.execute(
        f"SELECT {_SOURCE_COLUMNS} FROM sources WHERE name = ?", (text,)
    ).fetchone()
    return dict(row) if row is not None else None


def touch_source(conn: sqlite3.Connection, source_id: int) -> None:
    """刷新来源的 updated_at（一次成功 update 后调用）。"""
    conn.execute(
        "UPDATE sources SET updated_at = ? WHERE id = ?", (_now(), source_id)
    )
    conn.commit()


# ----------------------------------------------------------------------
# 节点写入与查询
# ----------------------------------------------------------------------

def upsert_nodes(conn: sqlite3.Connection, nodes: list) -> dict:
    """把去重后的节点写入库中，按 fingerprint 判重。

    已存在的指纹：只更新 last_seen_at 并合并来源记录，计为重复；
    新指纹：插入 nodes 与 node_sources，计为新增。

    Returns:
        {"added": 新增数, "duplicates": 与库中已有节点重复数}
    """
    from . import dedup  # 延迟导入，避免模块级循环依赖

    added = 0
    duplicates = 0
    now = _now()
    for node in nodes:
        if not node.fingerprint:
            node.fingerprint = dedup.fingerprint(node)
        row = conn.execute(
            "SELECT id FROM nodes WHERE fingerprint = ?", (node.fingerprint,)
        ).fetchone()
        source_ids = list(node.source_ids)
        if node.source_id is not None and node.source_id not in source_ids:
            source_ids.append(node.source_id)
        if row is None:
            cur = conn.execute(
                "INSERT INTO nodes (source_id, name, protocol, server, port,"
                " fingerprint, options_json, first_seen_at, last_seen_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source_ids[0] if source_ids else None,
                    node.name,
                    node.protocol,
                    node.server,
                    node.port,
                    node.fingerprint,
                    json.dumps(node.options, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            node_id = int(cur.lastrowid)
            added += 1
        else:
            node_id = int(row["id"])
            conn.execute(
                "UPDATE nodes SET last_seen_at = ? WHERE id = ?", (now, node_id)
            )
            duplicates += 1
        for sid in source_ids:
            conn.execute(
                "INSERT OR IGNORE INTO node_sources (node_id, source_id)"
                " VALUES (?, ?)",
                (node_id, sid),
            )
    conn.commit()
    return {"added": added, "duplicates": duplicates}


def list_nodes(conn: sqlite3.Connection, *, source_id: int | None = None) -> list:
    """列出节点（可按来源过滤，经 node_sources 关联），返回 Node 列表。"""
    from .models import Node

    if source_id is None:
        rows = conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT n.* FROM nodes n JOIN node_sources ns ON ns.node_id = n.id"
            " WHERE ns.source_id = ? ORDER BY n.id",
            (source_id,),
        ).fetchall()
    nodes: list[Node] = []
    for row in rows:
        links = conn.execute(
            "SELECT source_id FROM node_sources WHERE node_id = ? ORDER BY source_id",
            (row["id"],),
        ).fetchall()
        nodes.append(
            Node(
                name=row["name"],
                protocol=row["protocol"],
                server=row["server"],
                port=row["port"],
                source_id=row["source_id"],
                source_ids=[link["source_id"] for link in links],
                options=json.loads(row["options_json"] or "{}"),
                fingerprint=row["fingerprint"] or "",
            )
        )
    return nodes


def node_stats(conn: sqlite3.Connection) -> dict:
    """节点统计：总数、按协议、按来源（来源名 -> 节点数）。"""
    by_protocol = {
        row["protocol"]: int(row["c"])
        for row in conn.execute(
            "SELECT protocol, COUNT(*) AS c FROM nodes GROUP BY protocol"
            " ORDER BY protocol"
        ).fetchall()
    }
    by_source = {
        row["name"]: int(row["c"])
        for row in conn.execute(
            "SELECT s.name AS name, COUNT(*) AS c FROM node_sources ns"
            " JOIN sources s ON s.id = ns.source_id"
            " GROUP BY s.name ORDER BY s.name"
        ).fetchall()
    }
    return {
        "total": count_nodes(conn),
        "by_protocol": by_protocol,
        "by_source": by_source,
    }
