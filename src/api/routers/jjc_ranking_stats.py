from __future__ import annotations

import json
import os
from typing import Any, Optional

from fastapi import APIRouter, Query

from src.api.response import error_response, success_response


router = APIRouter(prefix="/api/jjc", tags=["jjc"])


@router.get("/ranking-stats")
async def get_ranking_stats(
    action: str = Query("list", description="list 或 read"),
    timestamp: Optional[str] = Query(None, description="read 模式下的时间戳"),
) -> dict[str, Any]:
    stats_dir = os.path.join("data", "jjc_ranking_stats")
    if not os.path.isdir(stats_dir):
        return error_response("stats_dir_not_found")

    action = action.strip().lower()
    if action == "list":
        files = [f for f in os.listdir(stats_dir) if f.endswith(".json")]
        timestamps: list[int] = []
        for filename in files:
            name = filename[:-5]
            if name.isdigit():
                timestamps.append(int(name))
        timestamps.sort(reverse=True)
        return success_response(timestamps)

    if action == "read":
        if not timestamp or not timestamp.isdigit():
            return error_response("invalid_timestamp")

        file_path = os.path.join(stats_dir, f"{timestamp}.json")
        if not os.path.isfile(file_path):
            return error_response("not_found")

        try:
            with open(file_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except Exception:
            return error_response("read_failed")

        return success_response(payload)

    return error_response("invalid_action")
