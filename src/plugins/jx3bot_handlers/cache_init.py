from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Awaitable, Callable

from nonebot import logger


def register(
    driver: Any,
    *,
    download_json: Callable[[], Awaitable[Any]],
    jiaoyiget: Callable[..., Awaitable[Any]],
    token: str,
    server_data_file: str,
    jjc_ranking_cache_file: str,
    jjc_ranking_cache_duration: int,
    set_server_data_cache: Callable[[Any], None],
    set_token_data: Callable[[Any], None],
) -> None:
    @driver.on_startup
    async def init_cache() -> None:
        try:
            await download_json()

            fresh_data = await jiaoyiget("https://www.jx3api.com/data/server/check")
            token_data = await jiaoyiget(
                f"https://www.jx3api.com/data/token/web-token?token={token}"
            )
            set_token_data(token_data)

            data_obj = json.loads(fresh_data) if isinstance(fresh_data, str) else fresh_data

            os.makedirs(os.path.dirname(os.path.abspath(server_data_file)), exist_ok=True)
            with open(server_data_file, "w", encoding="utf-8") as file_handle:
                json.dump(data_obj, file_handle, ensure_ascii=False, indent=2)

            set_server_data_cache(data_obj)
            logger.info(f"服务器数据已获取并保存到: {server_data_file}")

            if isinstance(token_data, dict):
                try:
                    import src.utils.shared_data

                    src.utils.shared_data.tokendata = token_data["data"]["limit"]
                    logger.info(f"token剩余：{src.utils.shared_data.tokendata}")
                except Exception:
                    logger.debug("token_data 结构不符合预期，跳过 tokendata 写入")

        except Exception as exc:
            logger.warning(f"获取新数据失败: {exc}")
            try:
                if os.path.exists(server_data_file):
                    with open(server_data_file, "r", encoding="utf-8") as file_handle:
                        set_server_data_cache(json.load(file_handle))
                    logger.info("已从本地文件加载服务器数据")
                else:
                    logger.warning("本地文件不存在，无法加载服务器数据")
            except Exception as read_error:
                logger.warning(f"读取本地文件失败: {read_error}")

        try:
            if os.path.exists(jjc_ranking_cache_file):
                with open(jjc_ranking_cache_file, "r", encoding="utf-8") as file_handle:
                    cached_data = json.load(file_handle)

                current_time = time.time()
                cache_time = cached_data.get("cache_time", 0)

                if current_time - cache_time < jjc_ranking_cache_duration:
                    logger.info(
                        "竞技场排行榜文件缓存有效，缓存时间: "
                        f"{datetime.fromtimestamp(cache_time).strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    logger.info("竞技场排行榜文件缓存已过期")
            else:
                logger.info("竞技场排行榜缓存文件不存在")
        except Exception as exc:
            logger.warning(f"检查竞技场排行榜缓存失败: {exc}")

