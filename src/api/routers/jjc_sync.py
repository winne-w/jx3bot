from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from nonebot import logger

from src.api.response import error_response, success_response
from src.services.jx3.singletons import jjc_match_data_sync_service


router = APIRouter(prefix="/api/jjc/sync", tags=["jjc-sync"])


def _sync_response(result: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(result, dict) and result.get("error"):
        return error_response(
            str(result.get("message") or "sync_service_error"),
            data=result,
        )
    return success_response(result)


@router.get("/status")
async def get_jjc_sync_status() -> Dict[str, Any]:
    try:
        return _sync_response(await jjc_match_data_sync_service.queue_status())
    except Exception as exc:
        logger.warning("JJC sync status call failed: error={}", exc)
        return error_response("sync_service_call_failed", data={"error": str(exc)})


@router.get("/queue")
async def list_jjc_sync_queue(
    status: Optional[str] = Query(None, description="队列状态过滤"),
    mode: Optional[str] = Query(None, description="同步类型过滤"),
    server: Optional[str] = Query(None, description="服务器名称搜索"),
    name: Optional[str] = Query(None, description="角色名称搜索"),
    page: int = Query(1, ge=1, description="分页页码"),
    page_size: int = Query(50, ge=1, le=200, description="分页大小"),
) -> Dict[str, Any]:
    normalized_status = (status or "").strip() or None
    normalized_mode = (mode or "").strip() or None
    normalized_server = (server or "").strip() or None
    normalized_name = (name or "").strip() or None
    try:
        result = await jjc_match_data_sync_service.list_queue(
            status=normalized_status,
            mode=normalized_mode,
            server=normalized_server,
            name=normalized_name,
            page=page,
            page_size=page_size,
        )
        return _sync_response(result)
    except Exception as exc:
        logger.warning("JJC sync queue call failed: error={}", exc)
        return error_response("sync_service_call_failed", data={"error": str(exc)})


@router.get("/workers")
async def list_jjc_sync_workers() -> Dict[str, Any]:
    try:
        return _sync_response(await jjc_match_data_sync_service.list_workers())
    except Exception as exc:
        logger.warning("JJC sync workers call failed: error={}", exc)
        return error_response("sync_service_call_failed", data={"error": str(exc)})
