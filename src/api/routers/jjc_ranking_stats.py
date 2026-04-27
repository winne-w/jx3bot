from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Query

from src.api.response import error_response, success_response


router = APIRouter(prefix="/api/jjc", tags=["jjc"])


def _stats_dir() -> str:
    return os.path.join("data", "jjc_ranking_stats")


def _summary_path(timestamp: str) -> str:
    return os.path.join(_stats_dir(), timestamp, "summary.json")


def _details_path(timestamp: str, range_key: str, lane: str, kungfu: str) -> str:
    return os.path.join(_stats_dir(), timestamp, "details", range_key, lane, f"{quote(kungfu, safe='')}.json")


def _legacy_path(timestamp: str) -> str:
    return os.path.join(_stats_dir(), f"{timestamp}.json")


def _load_json(file_path: str) -> dict[str, Any] | list[Any] | None:
    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except Exception:
        return None


def _build_summary_from_legacy(payload: dict[str, Any]) -> dict[str, Any]:
    summary_payload = {
        key: value
        for key, value in payload.items()
        if key != "kungfu_statistics"
    }
    summary_payload["kungfu_statistics"] = {}

    kungfu_statistics = payload.get("kungfu_statistics") or {}
    for range_key, range_stats in kungfu_statistics.items():
        if not isinstance(range_stats, dict):
            summary_payload["kungfu_statistics"][range_key] = range_stats
            continue

        summary_range: dict[str, Any] = {
            key: value
            for key, value in range_stats.items()
            if key not in {"healer", "dps"}
        }
        for lane_name in ("healer", "dps"):
            lane = range_stats.get(lane_name) or {}
            if not isinstance(lane, dict):
                summary_range[lane_name] = lane
                continue

            members_map = lane.get("members") or {}
            legendary_count_map: dict[str, int] = {}
            for kungfu, members in members_map.items():
                legendary_count_map[kungfu] = sum(
                    1 for member in (members or []) if str((member or {}).get("weapon_quality")) == "5"
                )

            summary_lane = {
                key: value
                for key, value in lane.items()
                if key != "members"
            }
            summary_lane["legendary_count_map"] = legendary_count_map
            summary_range[lane_name] = summary_lane

        summary_payload["kungfu_statistics"][range_key] = summary_range

    return summary_payload


def _extract_detail_from_legacy(
    payload: dict[str, Any],
    *,
    range_key: str,
    lane: str,
    kungfu: str,
) -> dict[str, Any] | None:
    range_stats = (payload.get("kungfu_statistics") or {}).get(range_key) or {}
    lane_stats = range_stats.get(lane) or {}
    members_map = lane_stats.get("members") or {}
    if not isinstance(members_map, dict):
        return None
    members = members_map.get(kungfu)
    if members is None:
        return None
    return {
        "range": range_key,
        "lane": lane,
        "kungfu": kungfu,
        "members": members,
    }


@router.get("/ranking-stats")
async def get_ranking_stats(
    action: str = Query("list", description="list 或 read"),
    timestamp: Optional[str] = Query(None, description="read 模式下的时间戳"),
) -> dict[str, Any]:
    stats_dir = _stats_dir()
    if not os.path.isdir(stats_dir):
        return error_response("stats_dir_not_found")

    action = action.strip().lower()
    if action == "list":
        timestamps: set[int] = set()
        for filename in os.listdir(stats_dir):
            if filename.endswith(".json"):
                name = filename[:-5]
                if name.isdigit():
                    timestamps.add(int(name))
                continue
            if filename.isdigit() and os.path.isdir(os.path.join(stats_dir, filename)):
                timestamps.add(int(filename))
        ordered = sorted(timestamps, reverse=True)
        return success_response(ordered)

    if action == "read":
        if not timestamp or not timestamp.isdigit():
            return error_response("invalid_timestamp")

        summary_path = _summary_path(timestamp)
        if os.path.isfile(summary_path):
            payload = _load_json(summary_path)
            if payload is None:
                return error_response("read_failed")
            return success_response(payload)

        legacy_path = _legacy_path(timestamp)
        if not os.path.isfile(legacy_path):
            return error_response("not_found")

        payload = _load_json(legacy_path)
        if not isinstance(payload, dict):
            return error_response("read_failed")
        return success_response(_build_summary_from_legacy(payload))

    return error_response("invalid_action")


@router.get("/ranking-stats/details")
async def get_ranking_stats_details(
    timestamp: str = Query(..., description="统计时间戳"),
    range_key: str = Query(..., alias="range", description="排名范围，如 top_200"),
    lane: str = Query(..., description="healer 或 dps"),
    kungfu: str = Query(..., description="心法名称"),
) -> dict[str, Any]:
    if not timestamp.isdigit():
        return error_response("invalid_timestamp")

    lane = lane.strip().lower()
    if lane not in {"healer", "dps"}:
        return error_response("invalid_lane")

    kungfu = kungfu.strip()
    range_key = range_key.strip()
    if not kungfu or not range_key:
        return error_response("invalid_params")

    detail_path = _details_path(timestamp, range_key, lane, kungfu)
    if os.path.isfile(detail_path):
        payload = _load_json(detail_path)
        if payload is None:
            return error_response("read_failed")
        return success_response(payload)

    legacy_path = _legacy_path(timestamp)
    if not os.path.isfile(legacy_path):
        return error_response("not_found")

    payload = _load_json(legacy_path)
    if not isinstance(payload, dict):
        return error_response("read_failed")

    detail_payload = _extract_detail_from_legacy(payload, range_key=range_key, lane=lane, kungfu=kungfu)
    if detail_payload is None:
        return error_response("not_found")
    return success_response(detail_payload)
