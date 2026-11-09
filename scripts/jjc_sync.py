#!/usr/bin/env python3
"""JJC 同步管理命令行工具。

复用 /jjc同步* 的 service 能力；CLI start/worker 用于启动前台 worker，
不依赖 bot 启动，直接命令行执行。

用法:
    python scripts/jjc_sync.py single <服务器> <角色名> [--force] [--global_role_id=...] [--role_id=...] [--zone=...]
    python scripts/jjc_sync.py add <服务器> <角色名> [--priority=N] [--no-queue] [--global_role_id=...] [--role_id=...] [--zone=...]
    python scripts/jjc_sync.py enqueue [--mode=default|full] [--limit=N] [--days=N|--until=YYYY-MM-DD]
    python scripts/jjc_sync.py start [--limit=N] [--max-roles=N] [--minutes=N] [--idle-sleep=N] [--worker-id=...]
    python scripts/jjc_sync.py worker [--max-roles=N] [--minutes=N] [--idle-sleep=N] [--worker-id=...]
    python scripts/jjc_sync.py priority <服务器> <角色名> <priority>
    python scripts/jjc_sync.py queue [--status=queued] [--page=1] [--page-size=50]
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
from src.services.jx3.jjc_match_data_sync import resolve_queue_sync_until_time  # noqa: E402
from src.services.jx3.singletons import jjc_match_data_sync_service as svc  # noqa: E402


# ---- 子命令处理 ----

def _normalize_mode(mode: str) -> str:
    return "full" if mode == "default" else mode


def _resolve_cli_queue_sync_until_time(args: argparse.Namespace):
    try:
        return resolve_queue_sync_until_time(days=args.days, until=args.until)
    except ValueError as exc:
        if str(exc) == "queue_sync_window_conflict":
            logger.error("days 和 until 不能同时指定")
        else:
            logger.error("同步窗口参数错误，days 必须是正整数，until 支持 Unix 秒或 YYYY-MM-DD")
        sys.exit(1)


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
        priority=args.priority,
        queue=not args.no_queue,
    )
    if result.get("error"):
        logger.error("添加失败: %s", result.get("message"))
        sys.exit(1)
    logger.info(result.get("message"))


async def cmd_start(args: argparse.Namespace) -> None:
    await cmd_worker(args)


async def cmd_enqueue(args: argparse.Namespace) -> None:
    mode = _normalize_mode(args.mode)
    result = await svc.enqueue_roles(
        mode=mode,
        limit=args.limit,
        source="cli",
        queue_sync_until_time=_resolve_cli_queue_sync_until_time(args),
    )
    if result.get("error"):
        logger.error("入队失败: %s", result.get("message", "unknown_error"))
        sys.exit(1)

    if result.get("paused"):
        print("同步已暂停，角色已入队但 worker 暂不领取")
        if result.get("pause_reason"):
            print(f"暂停原因: {result.get('pause_reason')}")

    print(f"模式: {mode}  同步截止: {result.get('queue_sync_until_time') or '-'}  请求入队: {args.limit}  实际入队: {result.get('enqueued_roles', 0)}")
    print(f"恢复租约: {result.get('recovered_leases', 0)}")
    counts = result.get("counts", {})
    if counts:
        print(f"当前排队: {counts.get('queued', 0)}  同步中: {counts.get('syncing', 0)}")
    print(f"耗时: {result.get('elapsed_seconds', 0):.1f}s")


async def cmd_worker(args: argparse.Namespace) -> None:
    mode = "full"
    max_seconds = args.minutes * 60 if getattr(args, "minutes", 0) and args.minutes > 0 else 0
    max_roles = args.max_roles
    legacy_limit = getattr(args, "limit", None)
    if max_roles is None and legacy_limit is not None:
        max_roles = legacy_limit
    logger.info(
        "启动 JJC 同步 worker: idle_sleep=%s max_roles=%s max_seconds=%s",
        args.idle_sleep,
        max_roles,
        max_seconds,
    )
    result = await svc.run_worker(
        mode=mode,
        worker_id=args.worker_id,
        idle_sleep=args.idle_sleep,
        max_seconds=max_seconds,
        max_roles=max_roles,
    )
    if result.get("error"):
        logger.error("worker 退出(错误): %s", result.get("message", "unknown_error"))
        sys.exit(1)
    print(f"worker: {result.get('worker_id')}")
    print(f"停止原因: {result.get('stopped_reason')}")
    print(f"处理角色: {result.get('processed_roles', 0)}")
    print(f"空闲 tick: {result.get('idle_ticks', 0)}  暂停 tick: {result.get('paused_ticks', 0)}")
    print(f"耗时: {result.get('elapsed_seconds', 0):.1f}s")


async def cmd_status(args: argparse.Namespace) -> None:
    result = await svc.status()
    if result.get("error"):
        logger.error("查询失败: %s", result.get("message"))
        sys.exit(1)

    status_labels = {
        "pending": "待同步", "queued": "排队中", "syncing": "同步中", "cooldown": "冷却中",
        "exhausted": "已完成", "failed": "失败", "disabled": "已禁用",
    }
    print(f"全局状态: {'已暂停' if result.get('paused') else '未暂停'}")
    if result.get("pause_reason"):
        print(f"暂停原因: {result.get('pause_reason')}")
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
    print(f"worker: {'有活跃 worker' if result.get('worker_running') else '无活跃 worker'}")
    workers = result.get("workers", [])
    if workers:
        print("worker 列表:")
        for worker in workers[:10]:
            current = ""
            if worker.get("current_server") or worker.get("current_name"):
                current = f" {worker.get('current_server', '?')}/{worker.get('current_name', '?')}"
            status = worker.get("effective_status") or worker.get("status") or "?"
            print(f"  {worker.get('worker_id', '?')}: {status}{current}")


async def cmd_priority(args: argparse.Namespace) -> None:
    result = await svc.set_role_priority(
        server=args.server,
        name=args.name,
        priority=args.priority,
        updated_by="cli",
    )
    if result.get("error"):
        logger.error("优先级调整失败: %s", result.get("message"))
        sys.exit(1)
    logger.info(result.get("message"))


async def cmd_queue(args: argparse.Namespace) -> None:
    result = await svc.list_queue(
        status=args.status,
        page=args.page,
        page_size=args.page_size,
    )
    if result.get("error"):
        logger.error("队列查询失败: %s", result.get("message"))
        sys.exit(1)
    print(f"队列: page={result.get('page')} page_size={result.get('page_size')} total={result.get('total', 0)}")
    for item in result.get("items", [])[:args.page_size]:
        print(
            f"{item.get('status', '?'):8} "
            f"{item.get('priority', 0):5} "
            f"{item.get('server', '?')}/{item.get('name', '?')} "
            f"owner={item.get('lease_owner') or '-'}"
        )


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
    p_add.add_argument("--priority", type=int, default=100, help="调度优先级，默认 100")
    p_add.add_argument("--no-queue", action="store_true", help="只添加候选，不立即进入 queued 队列")

    # enqueue
    p_enqueue = sub.add_parser("enqueue", help="把候选角色批量放入 queued 队列")
    p_enqueue.add_argument("--mode", default="full", choices=["default", "full"])
    p_enqueue.add_argument("--limit", type=int, default=10, help="入队角色数，默认 10")
    p_enqueue.add_argument("--days", type=int, default=None, help="本次入队只同步最近 N 天")
    p_enqueue.add_argument("--until", default=None, help="本次入队同步到指定截止时间，支持 Unix 秒或 YYYY-MM-DD")

    # start / worker
    p_start = sub.add_parser("start", help="启动一个前台常驻 worker 处理 queued 队列")
    p_start.add_argument(
        "--limit",
        type=int,
        default=None,
        help="兼容旧参数：最多处理多少个角色；0 或不传表示不限数量，队列暂空时仍常驻等待",
    )
    p_start.add_argument("--max-roles", type=int, default=None, help="最多处理多少个角色，不传则常驻")
    p_start.add_argument("--minutes", type=int, default=0, help="最长运行分钟数，0 表示不限时")
    p_start.add_argument("--idle-sleep", type=int, default=10, help="空闲/暂停时 sleep 秒数")
    p_start.add_argument("--worker-id", default=None, help="自定义 worker_id")

    p_worker = sub.add_parser("worker", help="启动一个前台 worker 处理 queued 队列")
    p_worker.add_argument("--max-roles", type=int, default=None, help="最多处理多少个角色，不传则常驻")
    p_worker.add_argument("--minutes", type=int, default=0, help="最长运行分钟数，0 表示不限时")
    p_worker.add_argument("--idle-sleep", type=int, default=10, help="空闲/暂停时 sleep 秒数")
    p_worker.add_argument("--worker-id", default=None, help="自定义 worker_id")

    # priority
    p_priority = sub.add_parser("priority", help="调整角色同步优先级")
    p_priority.add_argument("server", help="服务器名称")
    p_priority.add_argument("name", help="角色名")
    p_priority.add_argument("priority", type=int, help="优先级")

    # queue
    p_queue = sub.add_parser("queue", help="查看同步队列")
    p_queue.add_argument("--status", default=None, help="按状态过滤，如 queued/syncing")
    p_queue.add_argument("--page", type=int, default=1)
    p_queue.add_argument("--page-size", type=int, default=50)

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
        "single", "add", "enqueue", "start", "worker", "priority", "queue",
        "status", "pause", "resume", "reset",
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
        "enqueue": cmd_enqueue,
        "start": cmd_start,
        "worker": cmd_worker,
        "priority": cmd_priority,
        "queue": cmd_queue,
        "status": cmd_status,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "reset": cmd_reset,
    }
    await handlers[args.command](args)


if __name__ == "__main__":
    asyncio.run(main())
