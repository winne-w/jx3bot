from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from nonebot import logger

from src.api.response import error_response, success_response
from src.infra.jx3api_get import list_server_catalog_items


router = APIRouter(prefix="/api/jx3", tags=["jx3"])


@router.get("/servers")
async def list_jx3_servers() -> Dict[str, Any]:
    try:
        servers = list_server_catalog_items()
        return success_response({
            "servers": servers,
            "total": len(servers),
        })
    except Exception as exc:
        logger.warning("读取 JX3 区服列表失败: error={}", exc)
        return error_response("server_catalog_unavailable")
