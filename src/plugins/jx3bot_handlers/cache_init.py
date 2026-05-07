from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Awaitable, Callable, Optional

from nonebot import logger


def _is_valid_server_data(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return False
    return any(isinstance(item, dict) and item.get("server") for item in data)


def register(
    driver: Any,
    *,
    download_json: Callable[[], Awaitable[Any]],
    jiaoyiget: Callable[..., Awaitable[Any]],
    token: str,
    server_data_file: str,
    set_server_data_cache: Callable[[Any], None],
    set_token_data: Callable[[Any], None],
    ensure_baizhan_skill_icons: Optional[Callable[[], Any]] = None,
) -> None:
    @driver.on_startup
    async def init_cache() -> None:
        try:
            await download_json()

            fresh_data = await jiaoyiget("https://www.jx3api.com/data/status/check")
            token_data = None

            data_obj = json.loads(fresh_data) if isinstance(fresh_data, str) else fresh_data
            if not _is_valid_server_data(data_obj):
                logger.warning(
                    "服务器数据接口返回无效内容，跳过覆盖本地缓存: payload_type={} payload={}",
                    type(data_obj).__name__,
                    data_obj,
                )
                raise ValueError("invalid_server_data_payload")

            os.makedirs(os.path.dirname(os.path.abspath(server_data_file)), exist_ok=True)
            with open(server_data_file, "w", encoding="utf-8") as file_handle:
                json.dump(data_obj, file_handle, ensure_ascii=False, indent=2)

            set_server_data_cache(data_obj)
            logger.info(f"服务器数据已获取并保存到: {server_data_file}")
            set_token_data(token_data)

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

        if ensure_baizhan_skill_icons is not None:
            try:
                result = await asyncio.to_thread(ensure_baizhan_skill_icons)
                logger.info(
                    "百战技能图标同步完成: "
                    f"total={result.total}, downloaded={result.downloaded}, "
                    f"skipped_exists={result.skipped_exists}, skipped_invalid={result.skipped_invalid}, "
                    f"failed={result.failed}"
                )
            except Exception as exc:
                logger.warning(f"百战技能图标同步失败: {exc}")

