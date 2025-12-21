from __future__ import annotations

from typing import Any, Annotated

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.params import RegexGroup

from src.renderers.jx3.image import apply_filters, render_and_send_template_image
from src.services.jx3.command_context import resolve_server_and_name
from src.utils.defget import fetch_json
from src.utils.money_format import convert_number
from src.utils.random_text import suijitext
from src.utils.time_utils import time_ago_fenzhong


def register(jiayi_matcher: Any, env: Environment) -> None:
    @jiayi_matcher.handle()
    async def jiayi_to_image(
        bot: Bot, event: Event, foo: Annotated[tuple[Any, ...], RegexGroup()]
    ) -> None:
        resolved = await resolve_server_and_name(bot, event, foo)
        if not resolved:
            return
        server, query_name = resolved

        query_name = (
            str(query_name)
            .replace("[", "")
            .replace("]", "")
            .replace("&#91;", "")
            .replace("&#93;", "")
            .replace(" ", "")
        )

        jsonid = await fetch_json(url=f"http://node.jx3box.com/item_merged/name/{query_name}")
        if jsonid.get("total") == 0:
            await bot.send(
                event,
                MessageSegment.at(event.user_id)
                + Message(
                    f"  => 查询失败\n未找到，{query_name}\n1,大部分物品不支持模糊搜索!\n2,可以直接游戏复制不需要删除[]!"
                ),
            )
            return

        first_item = (jsonid.get("list") or [{}])[0]
        icon_id = first_item.get("IconID")
        icon_url = f"http://icon.jx3box.com/icon/{icon_id}.png" if icon_id else None
        item_id = first_item.get("id")
        item_name = first_item.get("Name") or query_name
        description = first_item.get("Desc")
        if description is not None:
            description = (
                description.replace('<Text>text="', "")
                .replace('\\" font=105 </text>', "")
                .replace(" ", "")
            )

        newpm = await fetch_json(url=f"http://next2.jx3box.com/api/item-price/{item_id}/detail?server={server}")
        newpm = (newpm or {}).get("data", {}).get("prices", None)
        if newpm is not None:
            newpm = sorted(newpm, key=lambda item: item["n_count"], reverse=True)

        if newpm is None:
            await bot.send(
                event,
                MessageSegment.at(event.user_id)
                + Message(f"  => 查询失败\n未找到交易行，{item_name}，的价格，等待api更新！"),
            )
            return

        newxs = await fetch_json(url=f"http://next2.jx3box.com/api/item-price/{item_id}/logs?server={server}")
        if (
            newxs is not None
            and "data" in newxs
            and newxs["data"] is not None
            and "logs" in newxs["data"]
            and isinstance(newxs["data"]["logs"], list)
            and len(newxs["data"]["logs"]) > 0
            and newxs["data"]["logs"][0] is not None
        ):
            newxs = newxs["data"]["logs"][0]

        apply_filters(env, {"time": time_ago_fenzhong, "timego": convert_number})
        await render_and_send_template_image(
            bot,
            event,
            env=env,
            template_name="交易行查询.html",
            context={
                "newpm": newpm,
                "newxs": newxs,
                "ico": icon_url,
                "qufu": server,
                "mz": item_name,
                "text": suijitext(),
                "Desc": description,
            },
            width=800,
            height="ck",
        )
