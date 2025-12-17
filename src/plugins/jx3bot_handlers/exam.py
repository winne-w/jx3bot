from __future__ import annotations

from typing import Any, Annotated, Callable

from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.params import RegexGroup

from src.services.jx3.exam import format_questions_reply


def register(
    keju_matcher: Any,
    *,
    jiaoyiget: Callable[..., Any],
) -> None:
    @keju_matcher.handle()
    async def handle_keju(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        subject = foo[0]
        data = await jiaoyiget(
            f"https://www.jx3api.com/data/exam/answer?subject={subject}&limit=20"
        )
        check_question = format_questions_reply(data)
        await bot.send(
            event, MessageSegment.at(event.user_id) + Message(f"\n{check_question}")
        )
