"""服务层门面：把各模块能力收敛成一组稳定的业务操作。

CLI（以及未来的 GUI）只调用本层，不直接拼凑底层模块，保证核心逻辑
与界面解耦（任务书阶段 4 的扩展前提）。

已实现（阶段 1）：来源管理、来源更新（获取→解析→去重→入库）、
节点统计、配置生成（完整 profile / provider 两种）与校验发布。
未实现：节点测速与评分（阶段 2，见 tester / scorer 模块，接口保持
NotImplementedError）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import config_gen, config_validate, dedup, fetcher, parser, storage

DEFAULT_DB_PATH = Path("data") / "spm.db"
DEFAULT_OUTPUT_PATH = Path("output") / "smart-proxy.yaml"
DEFAULT_PROVIDER_PATH = Path("output") / "smart-proxy-provider.yaml"


@dataclass
class UpdateStats:
    """一次来源更新的统计（供 CLI 输出中文摘要）。"""

    source_name: str
    parsed: int = 0  # 成功解析出的节点数
    added: int = 0  # 新入库节点数
    duplicates: int = 0  # 与库中已有（或同批）重复数
    skipped_unsupported: int = 0  # 协议暂不支持而跳过数
    failed: int = 0  # 逐条解析失败数
    errors: list[str] = field(default_factory=list)


class SpmService:
    """Smart Proxy Manager 的业务门面。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # -- 基础设施 ------------------------------------------------------
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = storage.init_db(self.db_path)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- 来源管理（走 storage） ----------------------------------------
    def list_sources(self) -> list[dict]:
        return storage.list_sources(self._db())

    def add_source(
        self, *, name: str, kind: str, location: str, is_public: bool = False
    ) -> int:
        return storage.add_source(
            self._db(),
            name=name,
            kind=kind,
            location=location,
            is_public=is_public,
        )

    def find_source(self, identifier: str) -> dict | None:
        return storage.find_source(self._db(), identifier)

    def node_count(self) -> int:
        return storage.count_nodes(self._db())

    # -- 来源更新：获取 → 解析 → 去重 → 入库 ---------------------------
    def refresh_source(
        self,
        source_id: int,
        *,
        allow_private: bool = False,
        transport=None,
        resolver=None,
    ) -> UpdateStats:
        """下载/读取一个来源，解析去重后入库，返回统计。

        获取或整体解析失败时抛 fetcher.FetchError / parser.ParseError，
        数据库不写入任何本批数据（失败不污染已有节点）。
        """
        conn = self._db()
        source = storage.get_source(conn, source_id)
        if source is None:
            raise ValueError(f"来源不存在：id={source_id}")
        content = fetcher.fetch_source(
            source["location"],
            source["kind"],
            allow_private=allow_private,
            transport=transport,
            resolver=resolver,
        )
        result = parser.parse_subscription(content, source_id=source_id)
        unique = dedup.deduplicate(result.nodes)
        in_batch_duplicates = len(result.nodes) - len(unique)
        upsert = storage.upsert_nodes(conn, unique)
        storage.touch_source(conn, source_id)
        return UpdateStats(
            source_name=source["name"],
            parsed=len(result.nodes),
            added=upsert["added"],
            duplicates=upsert["duplicates"] + in_batch_duplicates,
            skipped_unsupported=result.skipped_unsupported,
            failed=result.failed,
            errors=list(result.errors),
        )

    def update_source_by_identifier(
        self, identifier: str, **kwargs
    ) -> UpdateStats:
        """按 id 或名称更新一个来源（CLI 入口）。"""
        source = self.find_source(identifier)
        if source is None:
            raise ValueError(f"来源不存在：{identifier}")
        return self.refresh_source(source["id"], **kwargs)

    # -- 统计 ------------------------------------------------------------
    def node_stats(self) -> dict:
        return storage.node_stats(self._db())

    def list_nodes(self, *, source_id: int | None = None) -> list:
        return storage.list_nodes(self._db(), source_id=source_id)

    # -- 配置生成与校验 --------------------------------------------------
    def generate_config(
        self,
        *,
        output: str | Path | None = None,
        provider_only: bool = False,
        source_id: int | None = None,
    ) -> Path:
        """从库中节点生成配置并校验发布，返回输出路径。

        库中无节点时抛 ValueError（拒绝生成空配置覆盖旧文件）；
        校验失败抛 config_validate.ConfigValidationError，原文件保留。
        """
        nodes = self.list_nodes(source_id=source_id)
        if not nodes:
            raise ValueError(
                "数据库中没有可用节点，拒绝生成空配置覆盖已有文件；"
                "请先用 `spm update` 导入订阅"
            )
        if provider_only:
            text = config_gen.generate_provider(nodes)
            target = Path(output) if output else DEFAULT_PROVIDER_PATH
        else:
            text = config_gen.generate_profile(nodes)
            target = Path(output) if output else DEFAULT_OUTPUT_PATH
        return config_validate.write_validated_profile(
            text, target, report_dir=target.parent
        )

    def validate_file(self, path: str | Path) -> list[str]:
        """校验一个已存在的配置文件，返回问题列表（空 = 通过）。"""
        target = Path(path)
        if not target.is_file():
            raise ValueError(f"配置文件不存在：{path}")
        return config_validate.validate_profile(
            target.read_text(encoding="utf-8-sig")
        )
