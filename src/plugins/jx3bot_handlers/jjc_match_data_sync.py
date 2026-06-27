from __future__ import annotations

from typing import Any, Dict, List, Optional

from nonebot.adapters.onebot.v11 import Bot, Event

from src.services.jx3.jjc_match_data_sync import resolve_queue_sync_until_time


def register(matcher: Any, sync_service: Any, admin_qq: List[int]) -> None:
    @matcher.handle()
    async def jjc_sync_admin(bot: Bot, event: Event) -> None:
        user_id = int(event.user_id)
        if user_id not in admin_qq:
            await bot.send(event, "无权限：仅管理员可执行 JJC 同步管理命令")
            return

        text = event.get_plaintext().strip()

        if text.startswith("/jjc同步添加"):
            await _cmd_add(bot, event, sync_service, text)
        elif text.startswith("/jjc同步开始"):
            await _cmd_start(bot, event, sync_service, text)
        elif text.startswith("/jjc同步优先级"):
            await _cmd_priority(bot, event, sync_service, text)
        elif text.startswith("/jjc同步状态"):
            await _cmd_status(bot, event, sync_service)
        elif text.startswith("/jjc同步暂停"):
            await _cmd_pause(bot, event, sync_service, text)
        elif text.startswith("/jjc同步恢复"):
            await _cmd_resume(bot, event, sync_service)
        elif text.startswith("/jjc同步重置"):
            await _cmd_reset(bot, event, sync_service, text)
        elif text.startswith("/jjc同步单人"):
            await _cmd_sync_single(bot, event, sync_service, text)
        else:
            await bot.send(event, "未知命令。支持: /jjc同步添加 /jjc同步开始 /jjc同步优先级 /jjc同步状态 /jjc同步暂停 /jjc同步恢复 /jjc同步重置 /jjc同步单人")


async def _parse_add_args(text: str):
    """解析 /jjc同步添加 的参数。"""
    parts = text.split()
    # parts[0] 是 "/jjc同步添加"
    positional: List[str] = []
    kwargs: dict = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            kwargs[key] = value
        else:
            positional.append(part)
    server = positional[0] if len(positional) > 0 else ""
    name = positional[1] if len(positional) > 1 else ""
    return server, name, kwargs


def _parse_int_kwarg(kwargs: Dict[str, str], key: str, default: int) -> Optional[int]:
    if key not in kwargs:
        return default
    try:
        return int(kwargs[key])
    except (ValueError, TypeError):
        return None


def _parse_bool_kwarg(kwargs: Dict[str, str], key: str, default: bool) -> Optional[bool]:
    value = kwargs.get(key)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "是", "开启"}:
        return True
    if normalized in {"0", "false", "no", "n", "否", "不", "关闭"}:
        return False
    return None


async def _cmd_add(bot: Bot, event: Event, svc: Any, text: str) -> None:
    server, name, kwargs = await _parse_add_args(text)
    if not server or not name:
        await bot.send(event, "用法: /jjc同步添加 <服务器> <角色名> [priority=100] [queued=1] [global_role_id=...] [role_id=...] [zone=...]")
        return
    priority = _parse_int_kwarg(kwargs, "priority", 100)
    if priority is None:
        await bot.send(event, "priority 必须是整数")
        return
    queue = _parse_bool_kwarg(kwargs, "queued", True)
    if queue is None:
        await bot.send(event, "queued 必须是明确的布尔值，例如 queued=1 或 queued=0")
        return
    result = await svc.add_role(
        server=server,
        name=name,
        global_role_id=kwargs.get("global_role_id"),
        role_id=kwargs.get("role_id"),
        zone=kwargs.get("zone"),
        priority=priority,
        queue=queue,
    )
    if result["error"]:
        await bot.send(event, f"添加失败：{result['message']}")
    else:
        await bot.send(event, result["message"])


_STATUS_LABELS = {
    "pending": "待同步",
    "queued": "排队中",
    "syncing": "同步中",
    "cooldown": "冷却中",
    "exhausted": "已完成",
    "failed": "失败",
    "disabled": "已禁用",
}


async def _cmd_start(bot: Bot, event: Event, svc: Any, text: str) -> None:
    parsed = _parse_start_args(text)
    if parsed["error"]:
        await bot.send(event, str(parsed["message"]))
        return

    mode = parsed["mode"]
    limit = parsed["limit"]
    max_rounds = parsed["max_rounds"]
    background = parsed["background"]
    queue_sync_until_time = parsed["queue_sync_until_time"]

    result = await svc.enqueue_roles(
        mode=mode,
        limit=limit,
        source="qq_start",
        queue_sync_until_time=queue_sync_until_time,
    )
    await _send_enqueue_result(
        bot,
        event,
        result,
        ignored_legacy=bool(background or max_rounds is not None or parsed["rounds_auto"]),
    )


def _parse_start_args(text: str) -> Dict[str, Any]:
    parts = text.split()
    mode = "default"
    limit = 10
    max_rounds: Optional[int] = None
    max_minutes = 60
    queue_sync_days: Optional[int] = None
    queue_sync_until_raw: Optional[str] = None
    background = False
    rounds_auto = False

    for part in parts[1:]:
        if part in ("background", "后台"):
            background = True
            rounds_auto = True
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            if key == "limit":
                try:
                    limit = int(value)
                except ValueError:
                    return _start_usage("limit 必须是正整数")
            elif key == "rounds":
                if value == "auto":
                    max_rounds = None
                    rounds_auto = True
                else:
                    try:
                        max_rounds = int(value)
                    except ValueError:
                        return _start_usage("rounds 必须是正整数或 auto")
            elif key == "minutes":
                try:
                    max_minutes = int(value)
                except ValueError:
                    return _start_usage("minutes 必须是正整数")
            elif key == "seconds":
                return _start_usage("请使用 minutes 参数，例如 minutes=60")
            elif key == "days":
                try:
                    queue_sync_days = int(value)
                except ValueError:
                    return _start_usage("days 必须是正整数")
            elif key == "until":
                queue_sync_until_raw = value
            else:
                return _start_usage(f"未知参数: {key}")
            continue
        if mode == "default":
            mode = part
        else:
            return _start_usage(f"未知参数: {part}")

    if mode == "default":
        mode = "full"
    if mode not in ("full",):
        return _start_usage("mode 必须是 default/full")
    if limit < 1:
        return _start_usage("limit 必须是正整数")
    if limit > 200:
        return _start_usage("limit 最大为 200")
    if max_rounds is not None and max_rounds < 1:
        return _start_usage("rounds 必须是正整数或 auto")
    if max_minutes < 1:
        return _start_usage("minutes 必须是正整数")
    try:
        queue_sync_until_time = resolve_queue_sync_until_time(
            days=queue_sync_days,
            until=queue_sync_until_raw,
        )
    except ValueError as exc:
        if str(exc) == "queue_sync_window_conflict":
            return _start_usage("days 和 until 不能同时指定")
        return _start_usage("同步窗口参数错误，days 必须是正整数，until 支持 Unix 秒或 YYYY-MM-DD")
    return {
        "error": False,
        "mode": mode,
        "queue_sync_until_time": queue_sync_until_time,
        "limit": limit,
        "max_rounds": max_rounds,
        "max_minutes": max_minutes,
        "background": background,
        "rounds_auto": rounds_auto,
    }


def _start_usage(reason: str) -> Dict[str, Any]:
    return {
        "error": True,
        "message": (
            f"{reason}\n"
            "用法: /jjc同步开始 [default|full] "
            "[limit=10] [days=14|until=YYYY-MM-DD]\n"
            "说明: 当前命令只负责入队，实际处理由常驻 worker 进程领取"
        ),
    }


async def _send_enqueue_result(
    bot: Bot,
    event: Event,
    result: Dict[str, Any],
    ignored_legacy: bool = False,
) -> None:
    if result.get("error"):
        await bot.send(event, f"入队失败：{result.get('message', 'unknown_error')}")
        return

    lines: List[str] = ["JJC 同步已入队"]
    if result.get("paused"):
        lines[0] = "JJC 同步已暂停，角色已入队但 worker 暂不领取"
        reason = result.get("pause_reason")
        if reason:
            lines.append(f"暂停原因: {reason}")
    lines.append(f"模式: {result.get('mode', 'full')}")
    if result.get("queue_sync_until_time"):
        lines.append(f"同步截止: {result.get('queue_sync_until_time')}")
    lines.append(f"请求入队: {result.get('limit', 0)}")
    lines.append(f"实际入队: {result.get('enqueued_roles', 0)}")
    lines.append(f"恢复租约: {result.get('recovered_leases', 0)}")
    counts = result.get("counts") or {}
    if counts:
        queued = counts.get("queued", 0)
        syncing = counts.get("syncing", 0)
        lines.append(f"当前排队: {queued}，同步中: {syncing}")
    lines.append(f"worker: {'有活跃 worker' if result.get('worker_running') else '无活跃 worker'}")
    if ignored_legacy:
        lines.append("提示: rounds/background 参数在队列模式下已忽略")
    await bot.send(event, "\n".join(lines))


async def _cmd_status(bot: Bot, event: Event, svc: Any) -> None:
    result = await svc.status()
    if result["error"]:
        await bot.send(event, f"查询状态失败：{result['message']}")
        return

    lines: List[str] = ["JJC 同步状态"]
    lines.append(f"全局状态：{'已暂停' if result['paused'] else '未暂停'}")
    if result.get("pause_reason"):
        lines.append(f"暂停原因：{result.get('pause_reason')}")

    counts = result.get("counts", {})
    if counts:
        for status_key in sorted(counts):
            label = _STATUS_LABELS.get(status_key, status_key)
            lines.append(f"  {label}: {counts[status_key]}")
    else:
        lines.append("  无角色记录")

    recent_errors = result.get("recent_errors", [])
    if recent_errors:
        lines.append("最近错误（最多 5 条）:")
        for i, err in enumerate(recent_errors[:5], 1):
            srv = err.get("server", "?")
            nam = err.get("name", "?")
            msg = err.get("last_error", "?")
            lines.append(f"  {i}. {srv}/{nam}: {msg}")

    if result.get("worker_running"):
        lines.append("worker：有活跃 worker")
    else:
        lines.append("worker：无活跃 worker")

    if result.get("background_running") and not result.get("worker_running"):
        lines.append("兼容后台任务：运行中")
    elif not result.get("worker_running") and result.get("last_background_summary"):
        summary = result["last_background_summary"]
        reason = summary.get("stopped_reason") or "unknown"
        rounds = summary.get("rounds", 0)
        processed = summary.get("processed_roles", 0)
        lines.append(f"最近后台批量：已停止({reason})，轮数 {rounds}，处理角色 {processed}")

    workers = result.get("workers") or []
    if workers:
        active = [worker for worker in workers if worker.get("online")]
        lines.append(f"worker 可见: {len(workers)}，活跃: {len(active)}")
        for worker in workers[:5]:
            worker_id = str(worker.get("worker_id") or "?")
            status = str(worker.get("effective_status") or worker.get("status") or "?")
            server = str(worker.get("current_server") or "")
            name = str(worker.get("current_name") or "")
            current = f" {server}/{name}" if server or name else ""
            lines.append(f"  {worker_id}: {status}{current}")

    await bot.send(event, "\n".join(lines))


async def _cmd_priority(bot: Bot, event: Event, svc: Any, text: str) -> None:
    parts = text.split()
    if len(parts) < 4:
        await bot.send(event, "用法: /jjc同步优先级 <服务器> <角色名> <priority>")
        return
    server = parts[1]
    name = parts[2]
    try:
        priority = int(parts[3])
    except ValueError:
        await bot.send(event, "priority 必须是整数")
        return
    result = await svc.set_role_priority(
        server=server,
        name=name,
        priority=priority,
        updated_by=str(getattr(event, "user_id", "")) or None,
    )
    if result.get("error"):
        await bot.send(event, f"优先级调整失败：{result.get('message', 'unknown_error')}")
    else:
        await bot.send(event, result.get("message", f"优先级已调整为 {priority}"))


async def _cmd_pause(bot: Bot, event: Event, svc: Any, text: str) -> None:
    reason = text[len("/jjc同步暂停"):].strip()
    result = await svc.pause(reason)
    if result["error"]:
        await bot.send(event, f"暂停失败：{result['message']}")
    else:
        await bot.send(event, result["message"])


async def _cmd_resume(bot: Bot, event: Event, svc: Any) -> None:
    result = await svc.resume()
    if result["error"]:
        await bot.send(event, f"恢复失败：{result['message']}")
    else:
        await bot.send(event, result["message"])


async def _cmd_reset(bot: Bot, event: Event, svc: Any, text: str) -> None:
    parts = text.split()
    if len(parts) < 3:
        await bot.send(event, "用法: /jjc同步重置 <服务器> <角色名>")
        return
    server = parts[1]
    name = parts[2]
    result = await svc.reset_role(server=server, name=name)
    if result["error"]:
        await bot.send(event, f"重置失败：{result['message']}")
    else:
        await bot.send(event, result["message"])


async def _cmd_sync_single(bot: Bot, event: Event, svc: Any, text: str) -> None:
    server, name, kwargs = await _parse_add_args(text)
    if not server or not name:
        await bot.send(event, "用法: /jjc同步单人 <服务器> <角色名> [global_role_id=...] [role_id=...] [zone=...]")
        return
    await bot.send(event, f"开始同步 {server}/{name} ...")
    result = await svc.sync_single_role(
        server=server,
        name=name,
        global_role_id=kwargs.get("global_role_id"),
        role_id=kwargs.get("role_id"),
        zone=kwargs.get("zone"),
    )
    if result.get("error"):
        await bot.send(event, f"单人同步失败：{result.get('message', 'unknown_error')}")
        return

    lines: List[str] = [f"JJC 单人同步完成: {server}/{name}"]
    lines.append(f"发现对局: {result.get('discovered_matches', 0)}")
    lines.append(f"保存详情: {result.get('saved_details', 0)}")
    lines.append(f"跳过详情: {result.get('skipped_details', 0)}")
    lines.append(f"详情失败: {result.get('failed_details', 0)}")
    lines.append(f"详情不可用: {result.get('unavailable_details', 0)}")
    await bot.send(event, "\n".join(lines))
