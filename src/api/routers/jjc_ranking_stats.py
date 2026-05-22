from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import quote

from fastapi import APIRouter, Query
from nonebot import logger

from src.api.response import error_response, success_response
from src.services.jx3.singletons import jjc_ranking_inspect_service
from src.services.jx3.weapon_quality import extract_member_weapon_name, is_jjc_legendary_weapon
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo


router = APIRouter(prefix="/api/jjc", tags=["jjc"])


def _stats_dir() -> str:
    return os.path.join("data", "jjc_ranking_stats")


def _summary_path(timestamp: str) -> str:
    return os.path.join(_stats_dir(), timestamp, "summary.json")


def _details_path(timestamp: str, range_key: str, lane: str, kungfu: str) -> str:
    return os.path.join(_stats_dir(), timestamp, "details", range_key, lane, f"{quote(kungfu, safe='')}.json")


def _legacy_path(timestamp: str) -> str:
    return os.path.join(_stats_dir(), f"{timestamp}.json")


def _load_json(file_path: str) -> Optional[Union[dict[str, Any], List[Any]]]:
    try:
        with open(file_path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except Exception:
        return None


def _list_file_timestamps() -> List[int]:
    stats_dir = _stats_dir()
    if not os.path.isdir(stats_dir):
        return []

    timestamps: Set[int] = set()
    for filename in os.listdir(stats_dir):
        if filename.endswith(".json"):
            name = filename[:-5]
            if name.isdigit():
                timestamps.add(int(name))
            continue
        if filename.isdigit() and os.path.isdir(os.path.join(stats_dir, filename)):
            timestamps.add(int(filename))
    return sorted(timestamps, reverse=True)


def _paginate_timestamps(timestamps: List[int], page: int, page_size: int) -> Dict[str, Any]:
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    total = len(timestamps)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": timestamps[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": end < total,
    }


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
                    1
                    for member in (members or [])
                    if is_jjc_legendary_weapon(
                        (member or {}).get("weapon_quality"),
                        extract_member_weapon_name(member),
                    )
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
) -> Optional[dict[str, Any]]:
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
    page: Optional[int] = Query(None, ge=1, description="list 模式分页页码"),
    page_size: Optional[int] = Query(None, ge=1, le=100, description="list 模式分页大小"),
) -> dict[str, Any]:
    action = action.strip().lower()
    if action == "list":
        if page is not None or page_size is not None:
            normalized_page = page or 1
            normalized_page_size = page_size or 20
            mongo_result = await JjcRankingStatsRepo().list_timestamps(
                page=normalized_page,
                page_size=normalized_page_size,
            )
            if isinstance(mongo_result, dict) and mongo_result.get("total"):
                logger.info(
                    "JJC ranking stats list 命中 Mongo: page={} page_size={} total={}".format(
                        mongo_result.get("page"),
                        mongo_result.get("page_size"),
                        mongo_result.get("total"),
                    )
                )
                return success_response(mongo_result)
            file_timestamps = _list_file_timestamps()
            if file_timestamps:
                logger.info(
                    "JJC ranking stats list 回退文件: page={} page_size={} total={}".format(
                        normalized_page,
                        normalized_page_size,
                        len(file_timestamps),
                    )
                )
                return success_response(_paginate_timestamps(file_timestamps, normalized_page, normalized_page_size))
            logger.info(
                "JJC ranking stats list 未命中数据: page={} page_size={}".format(
                    normalized_page,
                    normalized_page_size,
                )
            )
            return success_response(mongo_result)

        mongo_timestamps = await JjcRankingStatsRepo().list_timestamps()
        file_timestamps = _list_file_timestamps()
        ordered = sorted(set(mongo_timestamps or []) | set(file_timestamps), reverse=True)
        if not ordered:
            logger.info("JJC ranking stats list 未命中数据")
            return error_response("stats_dir_not_found")
        logger.info(
            "JJC ranking stats list 合并数据: mongo_count={} file_count={} total={}".format(
                len(mongo_timestamps or []),
                len(file_timestamps),
                len(ordered),
            )
        )
        return success_response(ordered)

    if action == "read":
        if not timestamp or not timestamp.isdigit():
            return error_response("invalid_timestamp")

        mongo_payload = await JjcRankingStatsRepo().load_summary(int(timestamp))
        if mongo_payload is not None:
            logger.info("JJC ranking stats read 命中 Mongo: timestamp={}".format(timestamp))
            return success_response(mongo_payload)

        summary_path = _summary_path(timestamp)
        if os.path.isfile(summary_path):
            payload = _load_json(summary_path)
            if payload is None:
                return error_response("read_failed")
            logger.info("JJC ranking stats read 回退 summary 文件: timestamp={}".format(timestamp))
            return success_response(payload)

        legacy_path = _legacy_path(timestamp)
        if not os.path.isfile(legacy_path):
            logger.info("JJC ranking stats read 未命中数据: timestamp={}".format(timestamp))
            return error_response("not_found")

        payload = _load_json(legacy_path)
        if not isinstance(payload, dict):
            return error_response("read_failed")
        logger.info("JJC ranking stats read 回退 legacy 文件: timestamp={}".format(timestamp))
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

    mongo_payload = await JjcRankingStatsRepo().load_detail(
        int(timestamp),
        range_key,
        lane,
        kungfu,
    )
    if mongo_payload is not None:
        logger.info(
            "JJC ranking stats detail 命中 Mongo: timestamp={} range={} lane={} kungfu={}".format(
                timestamp,
                range_key,
                lane,
                kungfu,
            )
        )
        return success_response(mongo_payload)

    detail_path = _details_path(timestamp, range_key, lane, kungfu)
    if os.path.isfile(detail_path):
        payload = _load_json(detail_path)
        if payload is None:
            return error_response("read_failed")
        logger.info(
            "JJC ranking stats detail 回退 detail 文件: timestamp={} range={} lane={} kungfu={}".format(
                timestamp,
                range_key,
                lane,
                kungfu,
            )
        )
        return success_response(payload)

    legacy_path = _legacy_path(timestamp)
    if not os.path.isfile(legacy_path):
        logger.info(
            "JJC ranking stats detail 未命中数据: timestamp={} range={} lane={} kungfu={}".format(
                timestamp,
                range_key,
                lane,
                kungfu,
            )
        )
        return error_response("not_found")

    payload = _load_json(legacy_path)
    if not isinstance(payload, dict):
        return error_response("read_failed")

    detail_payload = _extract_detail_from_legacy(payload, range_key=range_key, lane=lane, kungfu=kungfu)
    if detail_payload is None:
        logger.info(
            "JJC ranking stats detail legacy 未命中: timestamp={} range={} lane={} kungfu={}".format(
                timestamp,
                range_key,
                lane,
                kungfu,
            )
        )
        return error_response("not_found")
    logger.info(
        "JJC ranking stats detail 回退 legacy 文件: timestamp={} range={} lane={} kungfu={}".format(
            timestamp,
            range_key,
            lane,
            kungfu,
        )
    )
    return success_response(detail_payload)


@router.get("/ranking-stats/role-recent")
async def get_ranking_stats_role_recent(
    server: str = Query(..., description="服务器名"),
    name: str = Query(..., description="角色名"),
    game_role_id: Optional[str] = Query(None, description="榜单角色 ID"),
    global_role_id: Optional[str] = Query(None, description="推栏全局角色 ID"),
    role_id: Optional[str] = Query(None, description="推栏角色 ID"),
    zone: Optional[str] = Query(None, description="区服分区"),
    cursor: int = Query(0, description="分页游标，0 表示第一页"),
    force_refresh: bool = Query(False, description="是否绕过缓存实时刷新第一页"),
) -> dict[str, Any]:
    server = server.strip()
    name = name.strip()
    if not server or not name:
        return error_response("invalid_params")

    result = await jjc_ranking_inspect_service.get_role_recent(
        server=server,
        name=name,
        cursor=cursor,
        identity_hints={
            "game_role_id": (game_role_id or "").strip() or None,
            "global_role_id": (global_role_id or "").strip() or None,
            "role_id": (role_id or "").strip() or None,
            "zone": (zone or "").strip() or None,
        },
        force_refresh=force_refresh,
    )
    if result.get("error"):
        return error_response(result.get("message") or result.get("error") or "unknown_error", data=result)
    return success_response(result)


@router.get("/ranking-stats/role-indicator")
async def get_ranking_stats_role_indicator(
    server: str = Query(..., description="服务器名"),
    name: str = Query(..., description="角色名"),
    game_role_id: Optional[str] = Query(None, description="榜单角色 ID"),
    global_role_id: Optional[str] = Query(None, description="推栏全局角色 ID"),
    role_id: Optional[str] = Query(None, description="推栏角色 ID"),
    zone: Optional[str] = Query(None, description="区服分区"),
    force_refresh: bool = Query(False, description="是否绕过缓存实时刷新"),
) -> dict[str, Any]:
    server = server.strip()
    name = name.strip()
    if not server or not name:
        return error_response("invalid_params")

    result = await jjc_ranking_inspect_service.get_role_indicator(
        server=server,
        name=name,
        game_role_id=(game_role_id or "").strip() or None,
        global_role_id=(global_role_id or "").strip() or None,
        role_id=(role_id or "").strip() or None,
        zone=(zone or "").strip() or None,
        force_refresh=force_refresh,
    )
    if result.get("error"):
        return error_response(result.get("message") or result.get("error") or "unknown_error", data=result)
    return success_response(result)


@router.get("/ranking-stats/match-detail")
async def get_ranking_stats_match_detail(
    match_id: str = Query(..., description="对局 ID"),
) -> dict[str, Any]:
    result = await jjc_ranking_inspect_service.get_match_detail(match_id=match_id)
    if result.get("error"):
        return error_response(result.get("message") or result.get("error") or "unknown_error", data=result)
    return success_response(result)
