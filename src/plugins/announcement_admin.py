from __future__ import annotations

from datetime import datetime

from config import ADMIN_QQ
from nonebot import on_command
from nonebot.params import CommandArg
from src.storage.mongo_repos.announcement_repo import AnnouncementRepo

_announcement_repo = AnnouncementRepo()

# ---- /公告添加 标题 | 内容 ----
announcement_add_cmd = on_command("公告添加", priority=5)


@announcement_add_cmd.handle()
async def handle_announcement_add(event, args=CommandArg()):
    user_id = event.get_user_id()
    if int(user_id) not in ADMIN_QQ:
        await announcement_add_cmd.finish("您没有权限管理公告")

    arg_text = args.extract_plain_text().strip()
    if "|" not in arg_text:
        await announcement_add_cmd.finish("用法: /公告添加 标题 | 内容")

    parts = arg_text.split("|", 1)
    title = parts[0].strip()
    content = parts[1].strip()

    if not title:
        await announcement_add_cmd.finish("标题不能为空")
    if not content:
        await announcement_add_cmd.finish("内容不能为空")

    date = datetime.now().strftime("%Y-%m-%d")
    announcement_id = await _announcement_repo.insert(
        title=title, content=content, date=date, created_by=user_id
    )
    if announcement_id is None:
        await announcement_add_cmd.finish("公告添加失败，请稍后重试")

    await announcement_add_cmd.finish(f"公告已添加\nID: {announcement_id}\n日期: {date}\n标题: {title}")


# ---- /公告列表 ----
announcement_list_cmd = on_command("公告列表", priority=5)


@announcement_list_cmd.handle()
async def handle_announcement_list(event):
    user_id = event.get_user_id()
    if int(user_id) not in ADMIN_QQ:
        await announcement_list_cmd.finish("您没有权限管理公告")

    result = await _announcement_repo.list_paginated(cursor=None, limit=5)
    announcements = result.get("announcements") or []

    if not announcements:
        await announcement_list_cmd.finish("暂无公告")

    lines = ["【最近公告】"]
    for i, a in enumerate(announcements):
        lines.append(f"ID: {a.get('announcement_id', '?')}")
        lines.append(f"日期: {a.get('date', '?')}")
        lines.append(f"标题: {a.get('title', '?')}")
        if i < len(announcements) - 1:
            lines.append("─────────────")

    if result.get("has_more"):
        lines.append("... 更多公告请查看公告页面")

    await announcement_list_cmd.finish("\n".join(lines))


# ---- /公告删除 <announcement_id> ----
announcement_delete_cmd = on_command("公告删除", priority=5)


@announcement_delete_cmd.handle()
async def handle_announcement_delete(event, args=CommandArg()):
    user_id = event.get_user_id()
    if int(user_id) not in ADMIN_QQ:
        await announcement_delete_cmd.finish("您没有权限管理公告")

    announcement_id = args.extract_plain_text().strip()
    if not announcement_id:
        await announcement_delete_cmd.finish("用法: /公告删除 <公告ID>")

    success = await _announcement_repo.delete_by_id(announcement_id)
    if success:
        await announcement_delete_cmd.finish(f"公告 {announcement_id} 已删除")
    else:
        await announcement_delete_cmd.finish(f"删除失败，请检查公告 ID 是否正确")
