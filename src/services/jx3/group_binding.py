from __future__ import annotations

from typing import Any, Optional

from nonebot import logger

from src.infra.mongo import get_db as _get_db
from src.storage.mongo_repos.group_config_repo import GroupConfigRepo


def _repo() -> GroupConfigRepo:
    return GroupConfigRepo(db=_get_db())


async def get_server_by_group(group_id: int | str, *, path: str = "") -> Optional[str]:
    group_id_str = str(group_id)
    try:
        config = await _repo().find_by_group(group_id_str)
        if config:
            return config.get("servers")
    except Exception as e:
        logger.warning("读取服务器绑定关系失败: group_id={}, error={}", group_id_str, e)
    return None
