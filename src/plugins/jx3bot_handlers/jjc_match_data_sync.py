from __future__ import annotations

from typing import Any, Dict, List, Optional

from nonebot.adapters.onebot.v11 import Bot, Event


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
        elif text.startswith("/jjc同步状态"):
            await _cmd_status(bot, event, sync_service)
        elif text.startswith("/jjc同步暂停"):
            await _cmd_pause(bot, event, sync_service, text)
        elif text.startswith("/jjc同步恢复"):
            await _cmd_resume(bot, event, sync_service)
        elif text.startswith("/jjc同步重置"):
            await _cmd_reset(bot, event, sync_service, text)
        else:
            await bot.send(event, "未知命令。支持: /jjc同步添加 /jjc同步开始 /jjc同步状态 /jjc同步暂停 /jjc同步恢复 /jjc同步重置")


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


async def _cmd_add(bot: Bot, event: Event, svc: Any, text: str) -> None:
    server, name, kwargs = await _parse_add_args(text)
    if not server or not name:
        await bot.send(event, "用法: /jjc同步添加 <服务器> <角色名> [global_role_id=...] [role_id=...] [zone=...]")
        return
    result = await svc.add_role(
        server=server,
        name=name,
        global_role_id=kwargs.get("global_role_id"),
        role_id=kwargs.get("role_id"),
        zone=kwargs.get("zone"),
    )
    if result["error"]:
        await bot.send(event, f"添加失败：{result['message']}")
    else:
        await bot.send(event, result["message"])


_STATUS_LABELS = {
    "pending": "待同步",
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
    max_minutes = parsed["max_minutes"]
    max_seconds = max_minutes * 60
    background = parsed["background"]

    if background:
        result = await svc.start_background_run(
            mode=mode,
            limit=limit,
            max_rounds=max_rounds,
            max_seconds=max_seconds,
        )
        if result.get("error"):
            await bot.send(event, f"后台同步启动失败：{result.get('message', 'unknown_error')}")
            return
        rounds_text = "auto" if max_rounds is None else str(max_rounds)
        await bot.send(
            event,
            "\n".join([
                "JJC 后台批量同步已启动",
                f"模式: {mode}",
                f"每轮角色: {limit}",
                f"最大轮数: {rounds_text}",
                f"最长运行: {max_minutes}分钟",
            ]),
        )
        return

    if max_rounds is not None or parsed["rounds_auto"]:
        result = await svc.run_until_idle(
            mode=mode,
            limit=limit,
            max_rounds=max_rounds,
            max_seconds=max_seconds,
        )
        await _send_sync_result(bot, event, result, title="JJC 同步批量结果")
        return

    result = await svc.run_once(mode=mode, limit=limit)
    await _send_sync_result(bot, event, result, title="JJC 同步本轮结果")


def _parse_start_args(text: str) -> Dict[str, Any]:
    parts = text.split()
    mode = "default"
    limit = 3
    max_rounds: Optional[int] = None
    max_minutes = 60
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
            else:
                return _start_usage(f"未知参数: {key}")
            continue
        if mode == "default":
            mode = part
        else:
            return _start_usage(f"未知参数: {part}")

    if mode == "default":
        mode = "incremental_or_full"
    if mode not in ("incremental_or_full", "full", "incremental"):
        return _start_usage("mode 必须是 default/full/incremental")
    if limit < 1:
        return _start_usage("limit 必须是正整数")
    if limit > 200:
        return _start_usage("limit 最大为 200")
    if max_rounds is not None and max_rounds < 1:
        return _start_usage("rounds 必须是正整数或 auto")
    if max_minutes < 1:
        return _start_usage("minutes 必须是正整数")
    return {
        "error": False,
        "mode": mode,
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
            "用法: /jjc同步开始 [default|full|incremental] "
            "[limit=3] [rounds=1|auto] [minutes=60] [background|后台]"
        ),
    }


async def _send_sync_result(bot: Bot, event: Event, result: Dict[str, Any], title: str) -> None:
    if result.get("error"):
        await bot.send(event, f"同步启动失败：{result.get('message', 'unknown_error')}")
        return

    lines: List[str] = [title]
    if result.get("paused"):
        lines.append("运行状态：已暂停，本轮未执行")
    if "rounds" in result:
        lines.append(f"执行轮数: {result.get('rounds', 0)}")
    if result.get("stopped_reason"):
        lines.append(f"停止原因: {result.get('stopped_reason')}")
    lines.append(f"恢复租约: {result.get('recovered_leases', 0)}")
    lines.append(f"处理角色: {result.get('processed_roles', 0)}")
    lines.append(f"发现对局: {result.get('discovered_matches', 0)}")
    lines.append(f"保存详情: {result.get('saved_details', 0)}")
    lines.append(f"跳过详情: {result.get('skipped_details', 0)}")
    lines.append(f"详情失败: {result.get('failed_details', 0)}")
    lines.append(f"详情不可用: {result.get('unavailable_details', 0)}")
    lines.append(f"失败角色: {result.get('failed_roles', 0)}")
    elapsed = result.get("elapsed_seconds")
    if isinstance(elapsed, (int, float)):
        lines.append(f"耗时: {elapsed:.1f}s")
    errors = result.get("errors") or []
    if errors:
        lines.append("错误:")
        for i, err in enumerate(errors[:5], 1):
            lines.append(f"  {i}. {err}")
    await bot.send(event, "\n".join(lines))


async def _cmd_status(bot: Bot, event: Event, svc: Any) -> None:
    result = await svc.status()
    if result["error"]:
        await bot.send(event, f"查询状态失败：{result['message']}")
        return

    lines: List[str] = ["JJC 同步状态"]
    lines.append(f"运行状态：{'已暂停' if result['paused'] else '运行中'}")

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

    if result.get("background_running"):
        lines.append("后台批量同步：运行中")
    elif result.get("last_background_summary"):
        summary = result["last_background_summary"]
        reason = summary.get("stopped_reason") or "unknown"
        rounds = summary.get("rounds", 0)
        processed = summary.get("processed_roles", 0)
        lines.append(f"最近后台批量：已停止({reason})，轮数 {rounds}，处理角色 {processed}")

    await bot.send(event, "\n".join(lines))


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
