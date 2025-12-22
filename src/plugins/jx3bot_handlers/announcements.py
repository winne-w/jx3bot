from __future__ import annotations

from typing import Any, Annotated, Callable

from nonebot.adapters.onebot.v11 import Bot, Event
from nonebot.params import RegexGroup

from src.services.jx3.announcements import format_time, parse_updates, parse_updateshuodong, parse_updatesnew


def register(
    huodong_matcher: Any,
    gengxin_matcher: Any,
    jigai_matcher: Any,
    *,
    jiaoyiget: Callable[..., Any],
    skill_records_url: str,
) -> None:
    @huodong_matcher.handle()
    async def handle_huodong(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            data = await jiaoyiget("https://www.jx3api.com/data/news/allnews?limit=50")
            records = parse_updateshuodong(data, keyword="活动")
            if not records:
                await bot.send(event, "未找活动相关公告")
                return

            msg_parts = ["【活动更新公告】"]
            for i, record in enumerate(records):
                formatted_time = format_time(record["time"])
                msg_parts.append(f"{i + 1}. {record['title']}")
                msg_parts.append(f"   发布时间: {formatted_time}")
                msg_parts.append(f"   查看原文: {record['url']}")
                if i < len(records) - 1:
                    msg_parts.append("─────────────")

            await bot.send(event, "\n".join(msg_parts))
        except Exception as exc:
            await bot.send(event, f"获取活动相关公告失败: {str(exc)[:100]}")

    @gengxin_matcher.handle()
    async def handle_gengxin(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            data = await jiaoyiget("https://www.jx3api.com/data/news/announce?limit=5")
            records = parse_updatesnew(data, keyword="版本")
            if not records:
                await bot.send(event, "未找到版本更新公告")
                return

            msg_parts = ["【版本更新公告】"]
            for i, record in enumerate(records):
                formatted_time = format_time(record["time"])
                msg_parts.append(f"{i + 1}. {record['title']}")
                msg_parts.append(f"   发布时间: {formatted_time}")
                msg_parts.append(f"   查看原文: {record['url']}")
                if i < len(records) - 1:
                    msg_parts.append("─────────────")

            await bot.send(event, "\n".join(msg_parts))
        except Exception as exc:
            await bot.send(event, f"版本更新公告失败: {str(exc)[:100]}")

    @jigai_matcher.handle()
    async def handle_jigai(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            data = await jiaoyiget(skill_records_url)
            records = parse_updates(data, keyword="武学")
            if not records:
                await bot.send(event, "未找到最新的武学调整公告")
                return

            msg_parts = ["【最新武学调整】"]
            for i, record in enumerate(records):
                formatted_time = format_time(record["time"])
                msg_parts.append(f"{i + 1}. {record['title']}")
                msg_parts.append(f"   发布时间: {formatted_time}")
                msg_parts.append(f"   查看原文: {record['url']}")
                if i < len(records) - 1:
                    msg_parts.append("─────────────")

            await bot.send(event, "\n".join(msg_parts))
        except Exception as exc:
            await bot.send(event, f"获取武学调整信息失败: {str(exc)[:100]}")
