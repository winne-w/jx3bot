from __future__ import annotations

from typing import Any, Annotated, Callable
from urllib.parse import urlencode

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
        uid = foo[0] if foo[0] is not None else foo[2]
        if not (uid.isascii() and uid.isdecimal() and 6 <= len(uid) <= 10 and 100000 <= int(uid) <= 4000000000):
            await bot.send(event, MessageSegment.at(event.user_id) + Message("\n请输入正确的角色UID（100000～4000000000）"))
            return

        params = {"uid": uid}
        if foo[0] is None:
            params["server"] = foo[1]
        query = urlencode(params)
        data = await get(f"https://www.jx3api.com/fraud/detail?{query}", token=token)
        formatted_reply = format_scammer_reply(data)
        await bot.send(event, MessageSegment.at(event.user_id) + Message(f"\n{formatted_reply}"))
