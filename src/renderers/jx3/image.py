from __future__ import annotations

from typing import Any

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot import logger

from src.infra.screenshot import jietu


def apply_filters(env: Environment, filters: dict[str, Any] | None) -> None:
    if not filters:
        return
    for name, fn in filters.items():
        env.filters[name] = fn


async def render_template_image(
    env: Environment,
    template_name: str,
    context: dict[str, Any],
    *,
    width: int,
    height: int | str = "ck",
) -> bytes:
    template = env.get_template(template_name)
    html_content = template.render(**context)
    return await jietu(html_content, width, height)


async def send_image(
    bot: Any,
    event: Any,
    image_bytes: bytes,
    *,
    at_user: bool = False,
    prefix: str | None = None,
) -> None:
    message = Message()
    if at_user and getattr(event, "user_id", None):
        message += MessageSegment.at(event.user_id)
    if prefix:
        message += Message(prefix)
    message += MessageSegment.image(image_bytes)
    await bot.send(event, message)


async def send_text(
    bot: Any,
    event: Any,
    text: str,
    *,
    at_user: bool = False,
) -> None:
    message = Message()
    if at_user and getattr(event, "user_id", None):
        message += MessageSegment.at(event.user_id)
    message += Message(text)
    await bot.send(event, message)


async def render_and_send_template_image(
    bot: Any,
    event: Any,
    *,
    env: Environment,
    template_name: str,
    context: dict[str, Any],
    width: int,
    height: int | str = "ck",
    at_user: bool = True,
    prefix: str | None = "   查询结果",
) -> None:
    try:
        image_bytes = await render_template_image(
            env,
            template_name,
            context,
            width=width,
            height=height,
        )
        await send_image(bot, event, image_bytes, at_user=at_user, prefix=prefix)
    except Exception:
        logger.exception("render_and_send_template_image failed: template={}", template_name)
        raise
