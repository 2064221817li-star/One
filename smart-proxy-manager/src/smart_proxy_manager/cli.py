"""CLI：命令行入口（console script ``spm``）。

只负责参数解析、调用服务层、输出结果与退出码，不写业务逻辑。
约定：
- 错误信息用中文，说明原因；
- 成功返回 0，参数错误由 argparse 返回 2，业务错误返回 1；
- 不要求管理员权限，不修改系统代理。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .services import DEFAULT_DB_PATH, SpmService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spm",
        description="Smart Proxy Manager — 智能代理节点管理（与 Clash Verge Rev / Mihomo 配合）",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite 数据库路径（默认: {DEFAULT_DB_PATH}）",
    )
    sub = parser.add_subparsers(dest="command")

    p_sources = sub.add_parser("sources", help="订阅来源管理")
    src_sub = p_sources.add_subparsers(dest="sources_command")
    src_sub.add_parser("list", help="列出全部来源")
    p_add = src_sub.add_parser("add", help="新增一个来源")
    p_add.add_argument("--name", required=True, help="来源名称（唯一）")
    p_add.add_argument(
        "--kind", required=True, choices=["url", "file"], help="来源类型"
    )
    p_add.add_argument("--location", required=True, help="订阅 URL 或本地文件路径")
    p_add.add_argument(
        "--public",
        action="store_true",
        help="标记为公开来源（与私人订阅隔离存放、隔离筛选）",
    )

    p_update = sub.add_parser(
        "update", help="更新来源：获取订阅 → 解析 → 去重 → 入库"
    )
    p_update.add_argument(
        "source", nargs="?", help="来源 id 或名称（与 --all 二选一）"
    )
    p_update.add_argument(
        "--all", action="store_true", help="更新全部已启用的来源"
    )
    p_update.add_argument(
        "--allow-private",
        action="store_true",
        help="允许订阅地址指向私网/回环地址（仅限自有局域网订阅，默认拒绝）",
    )

    sub.add_parser("stats", help="节点统计（按来源与协议）")

    p_gen = sub.add_parser("generate", help="从库中节点生成 Mihomo 配置")
    p_gen.add_argument(
        "--output",
        help="输出路径（默认：完整 profile 写 output/smart-proxy.yaml，"
        "provider 写 output/smart-proxy-provider.yaml）",
    )
    p_gen.add_argument(
        "--provider-only",
        action="store_true",
        help="只生成 provider 数据文件（仅 proxies 列表）",
    )
    p_gen.add_argument(
        "--source", help="只使用指定来源（id 或名称）的节点生成"
    )

    p_validate = sub.add_parser("validate", help="校验一个已有的配置文件")
    p_validate.add_argument("path", help="待校验的 YAML 配置文件路径")
    return parser


def _cmd_sources(args: argparse.Namespace, service: SpmService) -> int:
    if args.sources_command == "list":
        sources = service.list_sources()
        if not sources:
            print("（暂无来源，用 `spm sources add` 添加）")
            return 0
        for s in sources:
            scope = "公开" if s["is_public"] else "私人"
            state = "启用" if s["enabled"] else "停用"
            # 注意：location 可能是含 Token 的订阅地址，这里只在用户本机
            # 终端回显；禁止把该输出转存到会外传的日志（见 AGENTS.md）。
            print(
                f"[{s['id']}] {s['name']} | {s['kind']} | {scope} | {state} | {s['location']}"
            )
        return 0
    if args.sources_command == "add":
        try:
            new_id = service.add_source(
                name=args.name,
                kind=args.kind,
                location=args.location,
                is_public=args.public,
            )
        except sqlite3.IntegrityError:
            print(f"错误：来源名称已存在：{args.name}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        print(f"已添加来源 [{new_id}] {args.name}")
        return 0
    print("错误：请指定 sources 子命令（list / add），见 `spm sources --help`", file=sys.stderr)
    return 2


def _print_update_stats(stats) -> None:
    print(
        f"来源「{stats.source_name}」更新完成：解析 {stats.parsed} 条，"
        f"新增 {stats.added}，重复 {stats.duplicates}，"
        f"跳过（协议不支持） {stats.skipped_unsupported}，失败 {stats.failed}"
    )
    for error in stats.errors:
        print(f"  - {error}", file=sys.stderr)


def _cmd_update(args: argparse.Namespace, service: SpmService) -> int:
    from .fetcher import FetchError
    from .parser import ParseError

    if args.all and args.source:
        print("错误：来源参数与 --all 不能同时使用", file=sys.stderr)
        return 2
    if not args.all and not args.source:
        print("错误：请指定要更新的来源（id 或名称），或使用 --all", file=sys.stderr)
        return 2

    if args.source:
        try:
            stats = service.update_source_by_identifier(
                args.source, allow_private=args.allow_private
            )
        except (FetchError, ParseError, ValueError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        _print_update_stats(stats)
        return 0

    sources = [s for s in service.list_sources() if s["enabled"]]
    if not sources:
        print("（暂无已启用的来源）")
        return 0
    failed = 0
    for source in sources:
        try:
            stats = service.refresh_source(
                source["id"], allow_private=args.allow_private
            )
        except (FetchError, ParseError, ValueError) as exc:
            print(f"来源「{source['name']}」更新失败：{exc}", file=sys.stderr)
            failed += 1
            continue
        _print_update_stats(stats)
    if failed:
        print(f"共 {failed} 个来源更新失败", file=sys.stderr)
        return 1
    return 0


def _cmd_stats(args: argparse.Namespace, service: SpmService) -> int:
    stats = service.node_stats()
    print(f"节点总数：{stats['total']}")
    print("按协议：")
    if stats["by_protocol"]:
        for protocol, count in stats["by_protocol"].items():
            print(f"  {protocol}: {count}")
    else:
        print("  （无）")
    print("按来源：")
    if stats["by_source"]:
        for name, count in stats["by_source"].items():
            print(f"  {name}: {count}")
    else:
        print("  （无）")
    return 0


def _cmd_generate(args: argparse.Namespace, service: SpmService) -> int:
    from .config_validate import ConfigValidationError

    source_id = None
    if args.source:
        source = service.find_source(args.source)
        if source is None:
            print(f"错误：来源不存在：{args.source}", file=sys.stderr)
            return 1
        source_id = source["id"]
    try:
        target = service.generate_config(
            output=args.output,
            provider_only=args.provider_only,
            source_id=source_id,
        )
    except (ValueError, ConfigValidationError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    kind = "provider 数据文件" if args.provider_only else "完整 profile"
    print(f"已生成{kind}：{target}")
    return 0


def _cmd_validate(args: argparse.Namespace, service: SpmService) -> int:
    try:
        problems = service.validate_file(args.path)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    if problems:
        print(f"校验未通过，共 {len(problems)} 个问题：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"校验通过：{args.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    service = SpmService(Path(args.db))
    try:
        if args.command == "sources":
            return _cmd_sources(args, service)
        if args.command == "update":
            return _cmd_update(args, service)
        if args.command == "stats":
            return _cmd_stats(args, service)
        if args.command == "generate":
            return _cmd_generate(args, service)
        if args.command == "validate":
            return _cmd_validate(args, service)
        parser.print_help(sys.stderr)
        return 2
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
