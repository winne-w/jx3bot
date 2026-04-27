from __future__ import annotations

from fastapi import APIRouter

from src.api.response import success_response, error_response
from src.infra.mongo import health_check, get_db

router = APIRouter(prefix="/api/mongo", tags=["mongo-health"])


@router.get("/health")
async def mongo_health():
    """MongoDB 连通性诊断接口。验证 motor 安装、连接状态、集合列表。"""
    try:
        result = await health_check()
    except Exception as exc:
        return error_response("mongo_health_check_failed", data={"error": str(exc)})

    if result.get("connected"):
        return success_response(result)
    return error_response("mongo_not_connected", data=result)
