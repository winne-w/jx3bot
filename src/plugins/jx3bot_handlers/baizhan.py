from __future__ import annotations

import time
from typing import Any

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Bot, Event, Message

from config import API_URLS, TOKEN
from src.infra.jx3api_get import idget
from src.renderers.jx3.image import render_template_image, send_image, send_text
from src.services.jx3.baizhan import (
    baizhan_cache_paths,
    load_cached_baizhan_image_bytes,
    parse_role_baizhan_data,
    parse_baizhan_data,
    save_baizhan_cache,
)
from src.services.jx3.baizhan_skill_icons import build_skill_icon_index
from src.services.jx3.command_context import api_error_text
from src.services.jx3.group_binding import get_server_by_group
from src.services.jx3.query_context import build_baizhan_spec, build_role_baizhan_spec
from src.services.jx3.server_resolver import resolve_master_server_name
from src.utils.defget import get
from src.utils.random_text import suijitext


def register(baizhan_matcher: Any, env: Environment) -> None:
    @baizhan_matcher.handle()
    async def baizhan_to_image(bot: Bot, event: Event) -> None:
        message_text = event.get_plaintext().strip()
        args = message_text.split()
        if len(args) in (2, 3):
            if len(args) == 2:
                role_name = args[1]
                server = await get_server_by_group(getattr(event, "group_id", None) or "")
                if not server:
                    await send_text(
                        bot,
                        event,
                        "本群未绑定服务器，请先绑定服务器或使用：百战 服务器 角色名",
                        at_user=False,
                    )
                    return
            else:
                server, role_name = args[1], args[2]

            if not await idget(server):
                resolved_server = await resolve_master_server_name(server)
                if resolved_server != server:
                    server = resolved_server
            if not await idget(server):
                await send_text(bot, event, "   查询结果:请输入正确的服务器！", at_user=True)
                return

            items = await get(
                API_URLS["百战查询"],
                server=server,
                name=role_name,
                token=TOKEN,
            )
            if items.get("msg") != "success":
                await send_text(bot, event, api_error_text(items), at_user=True)
                return

            role_result = parse_role_baizhan_data(items, skill_icon_index=build_skill_icon_index())
            spec = build_role_baizhan_spec(result=role_result, random_text=suijitext())
            image_bytes = await render_template_image(
                env, spec.template_name, spec.context, width=spec.width, height=spec.height
            )
            await send_image(bot, event, image_bytes, at_user=True, prefix=spec.prefix or "   查询结果")
            return

        if len(args) != 1:
            await send_text(bot, event, "   用法: 百战 / 百战 角色名 / 百战 服务器 角色名", at_user=True)
            return

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
