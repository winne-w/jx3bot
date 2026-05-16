#!/usr/bin/env python3
"""JJC 同步管理命令行工具。

与 QQ 命令 /jjc同步* 使用完全相同的 service 和逻辑，
不依赖 bot 启动，直接命令行执行。

用法:
    python scripts/jjc_sync.py single <服务器> <角色名> [--force] [--global_role_id=...] [--role_id=...] [--zone=...]
    python scripts/jjc_sync.py add <服务器> <角色名> [--global_role_id=...] [--role_id=...] [--zone=...]
    python scripts/jjc_sync.py start [--mode=default|full|incremental] [--limit=N] [--rounds=N]
    python scripts/jjc_sync.py status
    python scripts/jjc_sync.py pause [--reason=...]
    python scripts/jjc_sync.py resume
    python scripts/jjc_sync.py reset <服务器> <角色名>

快捷方式：省略 single 子命令时默认执行单人同步
    python scripts/jjc_sync.py <服务器> <角色名> [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 日志配置（兼容 nonebot.logger 的 {} 格式化） ----
class _BraceFallbackFormatter(logging.Formatter):
    def format(self, record):
        if record.args and '{}' in str(record.msg):
            try:
                record.msg = str(record.msg).format(*record.args)
                record.args = ()
            except (ValueError, TypeError, KeyError, IndexError):
                pass
        return super().format(record)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _fix_root_handlers():
    for lg_name in [None, "nonebot"]:
        for handler in logging.getLogger(lg_name).handlers:
            if not isinstance(handler.formatter, _BraceFallbackFormatter):
                handler.setFormatter(_BraceFallbackFormatter(
                    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                ))


logger = logging.getLogger("jjc_sync")

# ---- 配置与依赖（复用 singletons.py，与 QQ 命令完全一致） ----
import config as cfg  # noqa: E402
from src.infra.mongo import init_mongo  # noqa: E402
from src.services.jx3.singletons import jjc_match_data_sync_service as svc  # noqa: E402


# ---- 子命令处理 ----

async def cmd_single(args: argparse.Namespace) -> None:
    if args.force:
        r = await svc.reset_role(server=args.server, name=args.name)
        if r.get("error"):
            logger.warning("强制重置失败（可能角色不存在）: %s", r.get("message"))
        else:
            logger.info("已重置角色冷却状态")

    logger.info("开始同步: server=%s name=%s", args.server, args.name)
    result = await svc.sync_single_role(
        server=args.server,
        name=args.name,
        global_role_id=args.global_role_id,
        role_id=args.role_id,
        zone=args.zone,
    )

    if result.get("error"):
        logger.error("同步失败: %s", result.get("message", "unknown_error"))
        sys.exit(1)

    logger.info("同步完成")
    print(f"角色: {args.server}/{args.name}")
    print(f"发现对局: {result.get('discovered_matches', 0)}")
    print(f"保存详情: {result.get('saved_details', 0)}")
    print(f"跳过详情: {result.get('skipped_details', 0)}")
    print(f"详情失败: {result.get('failed_details', 0)}")
    print(f"详情不可用: {result.get('unavailable_details', 0)}")


async def cmd_add(args: argparse.Namespace) -> None:
    result = await svc.add_role(
        server=args.server,
        name=args.name,
        global_role_id=args.global_role_id,
        role_id=args.role_id,
        zone=args.zone,
    )
    if result.get("error"):
        logger.error("添加失败: %s", result.get("message"))
        sys.exit(1)
    logger.info(result.get("message"))


async def cmd_start(args: argparse.Namespace) -> None:
    if args.rounds is not None or args.rounds_auto:
        result = await svc.run_until_idle(
            mode=args.mode,
            limit=args.limit,
            max_rounds=args.rounds,
            max_seconds=args.minutes * 60,
        )
    else:
        result = await svc.run_once(mode=args.mode, limit=args.limit)

    if result.get("error"):
        logger.error("同步失败: %s", result.get("message", "unknown_error"))
        sys.exit(1)

    rounds_text = str(result.get("rounds", 1))
    print(f"模式: {args.mode}  轮数: {rounds_text}  处理角色: {result.get('processed_roles', 0)}")
    print(f"发现对局: {result.get('discovered_matches', 0)}  保存详情: {result.get('saved_details', 0)}")
    print(f"跳过: {result.get('skipped_details', 0)}  失败: {result.get('failed_details', 0)}")
    print(f"耗时: {result.get('elapsed_seconds', 0):.1f}s")


async def cmd_status(args: argparse.Namespace) -> None:
    result = await svc.status()
    if result.get("error"):
        logger.error("查询失败: %s", result.get("message"))
        sys.exit(1)

    status_labels = {
        "pending": "待同步", "syncing": "同步中", "cooldown": "冷却中",
        "exhausted": "已完成", "failed": "失败", "disabled": "已禁用",
    }
    print(f"运行状态: {'已暂停' if result.get('paused') else '运行中'}")
    counts = result.get("counts", {})
    if counts:
        for key in sorted(counts):
            label = status_labels.get(key, key)
            print(f"  {label}: {counts[key]}")
    else:
        print("  无角色记录")

    recent_errors = result.get("recent_errors", [])
    if recent_errors:
        print("最近错误:")
        for i, err in enumerate(recent_errors[:5], 1):
            print(f"  {i}. {err.get('server', '?')}/{err.get('name', '?')}: {err.get('last_error', '?')}")


async def cmd_pause(args: argparse.Namespace) -> None:
    result = await svc.pause(args.reason or "")
    if result.get("error"):
        logger.error("暂停失败: %s", result.get("message"))
        sys.exit(1)
    logger.info(result.get("message"))


async def cmd_resume(args: argparse.Namespace) -> None:
    result = await svc.resume()
    if result.get("error"):
        logger.error("恢复失败: %s", result.get("message"))
        sys.exit(1)
    logger.info(result.get("message"))


async def cmd_reset(args: argparse.Namespace) -> None:
    result = await svc.reset_role(server=args.server, name=args.name)
    if result.get("error"):
        logger.error("重置失败: %s", result.get("message"))
        sys.exit(1)
    logger.info(result.get("message"))


# ---- 入口 ----

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="JJC 同步管理命令行工具（与 QQ /jjc同步* 命令等价）",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # single
    p_single = sub.add_parser("single", help="单人同步（立即执行，不入队列）")
    p_single.add_argument("server", help="服务器名称")
    p_single.add_argument("name", help="角色名")
    p_single.add_argument("--global_role_id", default=None)
    p_single.add_argument("--role_id", default=None)
    p_single.add_argument("--zone", default=None)
    p_single.add_argument("--force", action="store_true", help="强制同步，跳过冷却限制")

    # add
    p_add = sub.add_parser("add", help="添加角色到同步队列")
    p_add.add_argument("server", help="服务器名称")
    p_add.add_argument("name", help="角色名")
    p_add.add_argument("--global_role_id", default=None)
    p_add.add_argument("--role_id", default=None)
    p_add.add_argument("--zone", default=None)

    # start
    p_start = sub.add_parser("start", help="开始批量同步")
    p_start.add_argument("--mode", default="incremental_or_full",
                         choices=["incremental_or_full", "full", "incremental"])
    p_start.add_argument("--limit", type=int, default=3, help="每轮角色数，默认 3")
    p_start.add_argument("--rounds", type=int, default=None, help="最大轮数，不指定则执行一轮")
    p_start.add_argument("--rounds_auto", action="store_true", help="自动运行直到队列空闲")
    p_start.add_argument("--minutes", type=int, default=60, help="最长运行分钟数，默认 60")

    # status
    sub.add_parser("status", help="查看同步队列状态")

    # pause
    p_pause = sub.add_parser("pause", help="暂停全局同步")
    p_pause.add_argument("--reason", default=None)

    # resume
    sub.add_parser("resume", help="恢复全局同步")

    # reset
    p_reset = sub.add_parser("reset", help="重置角色同步进度")
    p_reset.add_argument("server", help="服务器名称")
    p_reset.add_argument("name", help="角色名")

    return parser


async def main() -> None:
    parser = build_parser()

    # 快捷方式：无子命令时当作 single 处理
    if len(sys.argv) >= 3 and sys.argv[1] not in (
        "single", "add", "start", "status", "pause", "resume", "reset",
        "-h", "--help",
    ):
        args = parser.parse_args(["single"] + sys.argv[1:])
    else:
        args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    _fix_root_handlers()
    logger.info("初始化 MongoDB: %s", cfg.MONGO_URI)
    await init_mongo(cfg.MONGO_URI)

    handlers = {
        "single": cmd_single,
        "add": cmd_add,
        "start": cmd_start,
        "status": cmd_status,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "reset": cmd_reset,
    }
    await handlers[args.command](args)


if __name__ == "__main__":
    asyncio.run(main())
