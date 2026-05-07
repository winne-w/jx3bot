from __future__ import annotations

from typing import Any, List

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
    parts = text.split()
    mode = parts[1] if len(parts) > 1 else "default"
    if mode == "default":
        mode = "incremental_or_full"
    if mode not in ("incremental_or_full", "full", "incremental"):
        await bot.send(event, "用法: /jjc同步开始 [default|full|incremental]")
        return

    result = await svc.run_once(mode=mode)
    if result.get("error"):
        await bot.send(event, f"同步启动失败：{result.get('message', 'unknown_error')}")
        return

    lines: List[str] = ["JJC 同步本轮结果"]
    if result.get("paused"):
        lines.append("运行状态：已暂停，本轮未执行")
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
