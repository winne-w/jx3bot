from __future__ import annotations

from typing import Optional

from nonebot import logger

import config as cfg
from src.infra.jx3api_get import get, idget


async def fetch_recent_arena(*, server: Optional[str], name: str) -> dict:
    resolved_server = server or cfg.DEFAULT_SERVER
    if not await idget(resolved_server):
        return {"error": "invalid_server", "message": "请输入正确的服务器！"}

    url = cfg.API_URLS.get("竞技查询")
    if not url:
        logger.warning("api_arena_recent missing url: key=竞技查询")
        return {"error": "missing_api_url", "message": "竞技查询 API 未配置"}

    logger.info("api_arena_recent fetch: server={} name={}", resolved_server, name)
    return await get(
        url=url,
        server=resolved_server,
        name=name,
        token=cfg.TOKEN,
        ticket=cfg.TICKET,
    )
