from __future__ import annotations

from typing import Any, Annotated, Callable

from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.params import RegexGroup

from src.services.jx3.fraud import format_scammer_reply


def register(
    pianzi_matcher: Any,
    *,
    get: Callable[..., Any],
    token: str,
) -> None:
    @pianzi_matcher.handle()
    async def handle_pianzi(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        uid = foo[0]
        if not uid.isdigit() or len(uid) < 5:
            await bot.send(event, MessageSegment.at(event.user_id) + Message("\n请正确输入要查询的QQ号码"))
            return

        data = await get(f"https://www.jx3api.com/data/fraud/detailed?uid={uid}", token=token)
        if data.get("code") != 200:
            formatted_reply = format_scammer_reply(data)
            await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n{formatted_reply}"))
            return

        await bot.send(event, MessageSegment.at(event.user_id) + Message("\n服务器访"))
