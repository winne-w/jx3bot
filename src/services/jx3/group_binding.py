from __future__ import annotations

import json
import os
from typing import Any

import aiofiles
from nonebot import logger


def load_groups(path: str = "groups.json") -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def get_server_by_group(group_id: int | str, *, path: str = "groups.json") -> str | None:
    group_id_str = str(group_id)
    if not os.path.exists(path):
        return None

    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            bindings = json.loads(await f.read())
        config = bindings.get(group_id_str) or {}
        return config.get("servers")
    except Exception as e:
        logger.warning("读取服务器绑定关系失败: group_id={}, error={}", group_id_str, e)
        return None
