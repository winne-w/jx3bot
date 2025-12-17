from __future__ import annotations

import time
from typing import Any

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Bot, Event, Message

from config import TOKEN
from src.renderers.jx3.image import render_template_image, send_image, send_text
from src.services.jx3.baizhan import (
    baizhan_cache_paths,
    load_cached_baizhan_image_bytes,
    parse_baizhan_data,
    save_baizhan_cache,
)
from src.services.jx3.command_context import api_error_text
from src.services.jx3.query_context import build_baizhan_spec
from src.utils.defget import get, suijitext


def register(baizhan_matcher: Any, env: Environment) -> None:
    @baizhan_matcher.handle()
    async def baizhan_to_image(bot: Bot, event: Event) -> None:
        current_timestamp = int(time.time())
        paths = baizhan_cache_paths()
        cached_bytes = load_cached_baizhan_image_bytes(paths, now_ts=current_timestamp)
        if cached_bytes:
            await send_image(bot, event, cached_bytes, at_user=True, prefix="   查询结果")
            return

        items = await get("https://www.jx3api.com/data/active/monster", token=TOKEN)
        if items.get("msg") != "success":
            await send_text(bot, event, api_error_text(items), at_user=True)
            return

        result = parse_baizhan_data(items)
        spec = build_baizhan_spec(result=result, random_text=suijitext())
        image_bytes = await render_template_image(
            env, spec.template_name, spec.context, width=spec.width, height=spec.height
        )
        save_baizhan_cache(paths, result=result, image_bytes=image_bytes)
        await send_image(bot, event, image_bytes, at_user=True, prefix=spec.prefix or "   查询结果")
