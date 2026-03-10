from __future__ import annotations

import json
import os
from typing import Any, Optional

from fastapi import APIRouter, Query

from src.api.response import error_response, success_response
from src.storage.singletons import jjc_ranking_stats_storage


router = APIRouter(prefix="/api/jjc", tags=["jjc"])


@router.get("/ranking-stats")
async def get_ranking_stats(
    action: str = Query("list", description="list 或 read"),
    timestamp: Optional[str] = Query(None, description="read 模式下的时间戳"),
) -> dict[str, Any]:
    stats_dir = os.path.join("data", "jjc_ranking_stats")

    action = action.strip().lower()
    if action == "list":
        timestamps = jjc_ranking_stats_storage.list_timestamps()
        if timestamps:
            return success_response(timestamps)
        if not os.path.isdir(stats_dir):
            return error_response("stats_dir_not_found")
        files = [f for f in os.listdir(stats_dir) if f.endswith(".json")]
        local_timestamps: list[int] = []
        for filename in files:
            name = filename[:-5]
            if name.isdigit():
                local_timestamps.append(int(name))
        local_timestamps.sort(reverse=True)
        return success_response(local_timestamps)

    if action == "read":
        if not timestamp or not timestamp.isdigit():
            return error_response("invalid_timestamp")

        mongo_payload = jjc_ranking_stats_storage.read(int(timestamp))
        if mongo_payload is not None:
            return success_response(mongo_payload)

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
