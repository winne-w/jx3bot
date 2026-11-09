from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

from src.api.response import error_response, success_response
from src.storage.mongo_repos.announcement_repo import AnnouncementRepo

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

_announcement_repo = AnnouncementRepo()


@router.get("/latest-date")
async def get_latest_date() -> dict[str, Any]:
    result = await _announcement_repo.find_latest_date_with_announcement()
    return success_response(result)


@router.get("/list")
async def list_announcements(
    cursor: Optional[str] = Query(None, description="分页游标，上一页最后一条的 created_at"),
    limit: int = Query(5, description="每页条数，1-50"),
) -> dict[str, Any]:
    if limit < 1 or limit > 50:
        return error_response("invalid_limit")

    cursor_float: Optional[float] = None
    if cursor is not None:
        try:
            cursor_float = float(cursor)
        except ValueError:
            return error_response("invalid_cursor")

    result = await _announcement_repo.list_paginated(cursor=cursor_float, limit=limit)
    return success_response(result)
