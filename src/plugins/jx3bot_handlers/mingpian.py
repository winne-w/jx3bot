from __future__ import annotations

import os
from typing import Any, Annotated

import aiofiles
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.params import RegexGroup

from config import TOKEN, API_URLS
from src.services.jx3.command_context import fetch_jx3api_or_reply_error, resolve_server_and_name
from src.services.jx3.mingpian import download_avatar_if_needed, extract_avatar_meta
from src.utils.defget import get_image


def register(mingpian_matcher: Any) -> None:
    @mingpian_matcher.handle()
    async def mingpianxiu_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        resolved = await resolve_server_and_name(bot, event, foo)
        if not resolved:
            return
        qufu, role_name = resolved

        mingpian_files = await get_image(qufu, role_name, free="1")

        if mingpian_files:
            latest_file = mingpian_files[0]
            try:
                async with aiofiles.open(latest_file, "rb") as f:
                    image_bytes = await f.read()
                await bot.send(
                    event,
                    MessageSegment.at(event.user_id)
                    + Message("   查询结果")
                    + MessageSegment.image(image_bytes),
                )
            except Exception as e:
                await bot.send(
                    event,
                    MessageSegment.at(event.user_id) + Message(f"   发送图片失败: {str(e)}"),
                )
            return

        items = await fetch_jx3api_or_reply_error(
            bot,
            event,
            url=API_URLS["名片查询"],
            server=qufu,
            name=role_name,
            token=TOKEN,
        )
        if not items:
            return

        avatar_url, image_name = extract_avatar_meta(items, server=qufu, role_name=role_name)
        img = await download_avatar_if_needed(avatar_url, image_name)
        if not img:
            await bot.send(event, MessageSegment.at(event.user_id) + Message("   查询结果为空：未获取到名片图片"))
            return
        await bot.send(
            event,
            MessageSegment.at(event.user_id) + Message("   查询结果") + MessageSegment.image(img),
        )
