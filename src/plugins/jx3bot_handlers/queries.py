from __future__ import annotations

from typing import Any, Annotated

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
    build_jjc_spec_or_text,
    build_qiyu_spec,
    build_yanhua_spec,
)
from src.utils.jjc_text import jjcdaxiaoxie
from src.utils.random_text import suijitext
from src.utils.time_format import format_minutes_seconds
from src.utils.time_utils import time_ago_filter, time_ago_fenzhong, timestamp_jjc


def register(
    *,
    env: Environment,
    yanhua_matcher: Any,
    qiyu_matcher: Any,
    zhuangfen_matcher: Any,
    jjc_matcher: Any,
    fuben_matcher: Any,
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
        await bot.send(
            event,
            MessageSegment.at(event.user_id)
            + Message("\n装备查询接口暂不可用：JX3API 当前没有可用的装备属性接口，暂时无法查询属性/装分。"),
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

        spec, error_text = build_jjc_spec_or_text(
            data=items,
            role_name=role_name,
            server=server,
            time_filter=time_ago_fenzhong,
            jjc_time_filter=jjcdaxiaoxie,
            duration_filter=format_minutes_seconds,
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
        await bot.send(
            event,
            MessageSegment.at(event.user_id)
            + Message("\n副本查询接口暂不可用：JX3API 当前没有可用的团队 CD 接口，暂时无法查询副本/秘境。"),
        )
