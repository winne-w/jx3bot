from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from jinja2 import Environment
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from src.renderers.jx3.image import render_and_send_template_image


def register(
    help_matcher: Any,
    env: Environment,
    *,
    group_config_file: str,
    bot_status: dict[str, Any],
    load_groups: Callable[[str], dict[str, Any]],
    format_time_duration: Callable[[float], str],
) -> None:
    @help_matcher.handle()
    async def handle_help(bot: Bot, event: GroupMessageEvent) -> None:
        gid = str(event.group_id)
        try:
            cfg = load_groups(group_config_file)
            if gid not in cfg:
                await help_matcher.finish("本群未绑定任何服务器")

            config = cfg[gid]
            group_info = await bot.get_group_info(group_id=event.group_id)
            group_name = group_info.get("group_name", "未知群名")
            group_avatar_url = f"http://p.qlogo.cn/gh/{event.group_id}/{event.group_id}/100"

            now = time.time()
            uptime = now - bot_status["startup_time"]
            uptime_str = format_time_duration(uptime)
            startup_time_str = datetime.fromtimestamp(bot_status["startup_time"]).strftime("%Y-%m-%d")

            last_offline = bot_status["last_offline_time"]
            if last_offline > 0:
                last_offline_str = datetime.fromtimestamp(last_offline).strftime("%Y-%m-%d")
                offline_duration_str = format_time_duration(bot_status["offline_duration"])
            else:
                last_offline_str = "无记录"
                offline_duration_str = "无记录"

            server = config.get("servers", "无")
            if not server:
                await help_matcher.finish("本群未绑定任何服务器")

            server_push = "开启" if config.get("开服推送", False) else "关闭"
            news_push = "开启" if config.get("新闻推送", False) else "关闭"
            records_push = "开启" if config.get("技改推送", False) else "关闭"
            daily_push = "开启" if config.get("日常推送", False) else "关闭"
            ranking_push = "开启" if config.get("竞技排名推送", False) else "关闭"

            await render_and_send_template_image(
                bot,
                event,
                env=env,
                template_name="qun.html",
                context={
                    "server": server,
                    "server_push": server_push,
                    "news_push": news_push,
                    "records_push": records_push,
                    "daily_push": daily_push,
                    "ranking_push": ranking_push,
                    "group_name": group_name,
                    "group_avatar_url": group_avatar_url,
                    "startup_time": startup_time_str,
                    "uptime": uptime_str,
                    "connection_count": int(bot_status["connection_count"]),
                    "last_offline": last_offline_str,
                    "offline_duration": offline_duration_str,
                    "last_connect": datetime.fromtimestamp(bot_status["last_connect_time"]).strftime("%Y-%m-%d"),
                },
                width=810,
                height="ck",
            )
        except Exception as e:
            await help_matcher.finish(f"获取帮助信息失败：{str(e)}")
