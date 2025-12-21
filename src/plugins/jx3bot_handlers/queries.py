from __future__ import annotations

from typing import Any, Callable, Awaitable, Annotated

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.params import RegexGroup

from config import API_URLS, TICKET, TOKEN
from src.renderers.jx3.image import apply_filters, render_and_send_template_image, send_text
from src.services.jx3.command_context import (
    CommandContextError,
    fetch_jx3api_or_raise,
    resolve_server_and_name,
)
from src.services.jx3.query_context import (
    build_fuben_spec,
    build_jjc_spec_or_text,
    build_qiyu_spec,
    build_yanhua_spec,
    build_zhuangfen_spec,
)
from src.utils.defget import get_image
from src.utils.jjc_text import jjcdaxiaoxie
from src.utils.random_text import suijitext
from src.utils.time_utils import time_ago_filter, time_ago_fenzhong, timestamp_jjc


def register(
    *,
    env: Environment,
    yanhua_matcher: Any,
    qiyu_matcher: Any,
    zhuangfen_matcher: Any,
    jjc_matcher: Any,
    fuben_matcher: Any,
    update_kuangfu_cache: Callable[[str, str, dict[str, Any]], Awaitable[None]],
) -> None:
    @yanhua_matcher.handle()
    async def yanhua_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            server, role_name = await resolve_server_and_name(foo, group_id=getattr(event, "group_id", None))
            items = await fetch_jx3api_or_raise(url=API_URLS["烟花查询"], server=server, name=role_name, token=TOKEN)
        except CommandContextError as exc:
            if exc.at_user:
                await bot.send(event, MessageSegment.at(event.user_id) + Message(exc.message))
            else:
                await bot.send(event, Message(exc.message))
            return

        spec = build_yanhua_spec(
            data=items,
            role_name=role_name,
            server=server,
            time_filter=time_ago_filter,
            random_text=suijitext(),
        )
        apply_filters(env, spec.filters)
        await render_and_send_template_image(
            bot,
            event,
            env=env,
            template_name=spec.template_name,
            context=spec.context,
            width=spec.width,
            height=spec.height,
            at_user=spec.at_user,
            prefix=spec.prefix,
        )

    @qiyu_matcher.handle()
    async def qiyu_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            server, role_name = await resolve_server_and_name(foo, group_id=getattr(event, "group_id", None))
            items = await fetch_jx3api_or_raise(
                url=API_URLS["奇遇查询"],
                server=server,
                name=role_name,
                token=TOKEN,
                ticket=TICKET,
            )
        except CommandContextError as exc:
            if exc.at_user:
                await bot.send(event, MessageSegment.at(event.user_id) + Message(exc.message))
            else:
                await bot.send(event, Message(exc.message))
            return

        spec = build_qiyu_spec(
            data=items,
            role_name=role_name,
            server=server,
            time_filter=time_ago_fenzhong,
            jjc_time_filter=timestamp_jjc,
            random_text=suijitext(),
        )
        apply_filters(env, spec.filters)
        await render_and_send_template_image(
            bot,
            event,
            env=env,
            template_name=spec.template_name,
            context=spec.context,
            width=spec.width,
            height=spec.height,
            at_user=spec.at_user,
            prefix=spec.prefix,
        )

    @zhuangfen_matcher.handle()
    async def zhuangfen_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            server, role_name = await resolve_server_and_name(foo, group_id=getattr(event, "group_id", None))
            items = await fetch_jx3api_or_raise(
                url=API_URLS["装备查询"],
                server=server,
                name=role_name,
                token=TOKEN,
                ticket=TICKET,
            )
        except CommandContextError as exc:
            if exc.at_user:
                await bot.send(event, MessageSegment.at(event.user_id) + Message(exc.message))
            else:
                await bot.send(event, Message(exc.message))
            return

        mpimg = await get_image(server, role_name)
        spec = build_zhuangfen_spec(
            data=items,
            role_name=role_name,
            server=server,
            random_text=suijitext(),
            mpimg=mpimg,
        )
        await render_and_send_template_image(
            bot,
            event,
            env=env,
            template_name=spec.template_name,
            context=spec.context,
            width=spec.width,
            height=spec.height,
            at_user=spec.at_user,
            prefix=spec.prefix,
        )

    @jjc_matcher.handle()
    async def jjc_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            server, role_name = await resolve_server_and_name(foo, group_id=getattr(event, "group_id", None))
            items = await fetch_jx3api_or_raise(
                url=API_URLS["竞技查询"],
                server=server,
                name=role_name,
                token=TOKEN,
                ticket=TICKET,
            )
        except CommandContextError as exc:
            if exc.at_user:
                await bot.send(event, MessageSegment.at(event.user_id) + Message(exc.message))
            else:
                await bot.send(event, Message(exc.message))
            return

        await update_kuangfu_cache(server, role_name, items)
        spec, error_text = build_jjc_spec_or_text(
            data=items,
            role_name=role_name,
            server=server,
            time_filter=time_ago_fenzhong,
            jjc_time_filter=jjcdaxiaoxie,
            random_text=suijitext(),
        )
        if error_text:
            await send_text(bot, event, error_text, at_user=True)
            return
        if not spec:
            return

        apply_filters(env, spec.filters)
        await render_and_send_template_image(
            bot,
            event,
            env=env,
            template_name=spec.template_name,
            context=spec.context,
            width=spec.width,
            height=spec.height,
            at_user=spec.at_user,
            prefix=spec.prefix,
        )

    @fuben_matcher.handle()
    async def fuben_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        try:
            server, role_name = await resolve_server_and_name(foo, group_id=getattr(event, "group_id", None))
            items = await fetch_jx3api_or_raise(
                url=API_URLS["副本查询"],
                server=server,
                name=role_name,
                token=TOKEN,
                ticket=TICKET,
            )
        except CommandContextError as exc:
            if exc.at_user:
                await bot.send(event, MessageSegment.at(event.user_id) + Message(exc.message))
            else:
                await bot.send(event, Message(exc.message))
            return

        spec = build_fuben_spec(
            data=items,
            role_name=role_name,
            server=server,
            random_text=suijitext(),
        )
        if not spec:
            await bot.send(
                event,
                MessageSegment.at(event.user_id)
                + Message(f"   查询结果: {server}，{role_name}，本周还没有清本！"),
            )
            return

        await render_and_send_template_image(
            bot,
            event,
            env=env,
            template_name=spec.template_name,
            context=spec.context,
            width=spec.width,
            height=spec.height,
            at_user=spec.at_user,
            prefix=spec.prefix,
        )
