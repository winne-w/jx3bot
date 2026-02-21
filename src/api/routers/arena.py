from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query
from nonebot import logger

from src.api.response import error_response, success_response
from src.services.jx3.arena_recent import fetch_recent_arena


router = APIRouter(prefix="/api/arena", tags=["arena"])


@router.get("/recent")
async def get_recent_arena(
    name: Optional[str] = Query(None, description="角色名"),
    server: Optional[str] = Query(None, description="服务器名，缺省使用默认服务器"),
) -> dict[str, Any]:
    if not name:
        return error_response("missing_name")

    logger.info("api_arena_recent request: server={} name={}", server, name)
    result = await fetch_recent_arena(server=server, name=name)

    if not isinstance(result, dict):
        return error_response("invalid_response", data={"raw": result})

    if result.get("error"):
        return error_response(result.get("message") or result.get("error"), data=result)

    if result.get("msg") != "success":
        return error_response(result.get("msg") or "unknown_error", data=result)

    return success_response(result)
