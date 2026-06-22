from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Query
from nonebot import logger

from config import KUNGFU_META
from src.api.response import error_response, success_response
from src.services.jx3.singletons import jjc_ranking_inspect_service
from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo
from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo


router = APIRouter(prefix="/api/jjc", tags=["jjc"])


_RANGE_LIMITS = {
    "top_1000": 1000,
    "top_200": 200,
    "top_100": 100,
    "top_50": 50,
}

_HEALER_KUNGFU_NAMES = {
    str(meta.get("name"))
    for meta in KUNGFU_META.values()
    if isinstance(meta, dict) and meta.get("category") == "healer" and meta.get("name")
}


def _build_peak_kungfu_statistics(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    lanes: Dict[str, Dict[str, Any]] = {
        "healer": {"distribution": {}, "valid_count": 0, "min_score": None},
        "dps": {"distribution": {}, "valid_count": 0, "min_score": None},
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        kungfu = str(item.get("kungfu") or "").strip()
        if not kungfu:
            kungfu = "未知心法"
        lane_key = "healer" if kungfu in _HEALER_KUNGFU_NAMES else "dps"
        lane = lanes[lane_key]
        lane["distribution"][kungfu] = int(lane["distribution"].get(kungfu, 0)) + 1
        lane["valid_count"] += 1
        score = item.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            lane["min_score"] = score if lane["min_score"] is None else min(lane["min_score"], score)

    for lane in lanes.values():
        lane["list"] = sorted(lane["distribution"].items(), key=lambda pair: pair[1], reverse=True)
        lane["legendary_count_map"] = {}
        if lane["min_score"] is None:
            lane["min_score"] = "-"
    return lanes


@router.get("/ranking-stats")
async def get_ranking_stats(
    action: str = Query("list", description="list 或 read"),
    timestamp: Optional[str] = Query(None, description="read 模式下的时间戳"),
    page: Optional[int] = Query(None, ge=1, description="list 模式分页页码"),
    page_size: Optional[int] = Query(None, ge=1, le=100, description="list 模式分页大小"),
    with_meta: bool = Query(False, description="list 模式返回元数据列表"),
) -> dict[str, Any]:
    action = action.strip().lower()
    if action == "list":
        if with_meta:
            normalized_page = page or 1
            normalized_page_size = page_size or 100
            mongo_result = await JjcRankingStatsRepo().list_timestamps(
                page=normalized_page,
                page_size=normalized_page_size,
                with_meta=True,
            )
            if isinstance(mongo_result, dict):
                logger.info(
                    "JJC ranking stats list with_meta: page={} page_size={} total={}".format(
                        mongo_result.get("page"),
                        mongo_result.get("page_size"),
                        mongo_result.get("total"),
                    )
                )
                return success_response(mongo_result)
            logger.info(
                "JJC ranking stats list with_meta 返回异常，返回空分页"
            )
            return success_response({
                "items": [],
                "page": normalized_page,
                "page_size": normalized_page_size,
                "total": 0,
                "has_more": False,
            })

        if page is not None or page_size is not None:
            normalized_page = page or 1
            normalized_page_size = page_size or 20
            mongo_result = await JjcRankingStatsRepo().list_timestamps(
                page=normalized_page,
                page_size=normalized_page_size,
            )
            if isinstance(mongo_result, dict):
                logger.info(
                    "JJC ranking stats list 读取 Mongo: page={} page_size={} total={}".format(
                        mongo_result.get("page"),
                        mongo_result.get("page_size"),
                        mongo_result.get("total"),
                    )
                )
                return success_response(mongo_result)
            logger.info(
                "JJC ranking stats list Mongo 读取异常，返回空分页: page={} page_size={}".format(
                    normalized_page,
                    normalized_page_size,
                )
            )
            return success_response({
                "items": [],
                "page": normalized_page,
                "page_size": normalized_page_size,
                "total": 0,
                "has_more": False,
            })

        mongo_timestamps = await JjcRankingStatsRepo().list_timestamps()
        if not mongo_timestamps:
            logger.info("JJC ranking stats list 未命中数据")
            return error_response("not_found")
        logger.info(
            "JJC ranking stats list 读取 Mongo: mongo_count={}".format(
                len(mongo_timestamps or []),
            )
        )
        return success_response(mongo_timestamps)

    if action == "read":
        if not timestamp or not timestamp.isdigit():
            return error_response("invalid_timestamp")

        mongo_payload = await JjcRankingStatsRepo().load_summary(int(timestamp))
        if mongo_payload is not None:
            logger.info("JJC ranking stats read 命中 Mongo: timestamp={}".format(timestamp))
            return success_response(mongo_payload)

        logger.info("JJC ranking stats read Mongo 未命中: timestamp={}".format(timestamp))
        return error_response("not_found")

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

    logger.info(
        "JJC ranking stats detail Mongo 未命中: timestamp={} range={} lane={} kungfu={}".format(
            timestamp,
            range_key,
            lane,
            kungfu,
        )
    )
    return error_response("not_found")


@router.get("/ranking-stats/flat-members")
async def get_ranking_stats_flat_members(
    timestamp: str = Query(..., description="统计时间戳"),
    range_key: str = Query("top_1000", alias="range", description="排名范围"),
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    if not timestamp.isdigit():
        return error_response("invalid_timestamp")
    range_key = range_key.strip()
    limit = _RANGE_LIMITS.get(range_key)
    if limit is None:
        return error_response("invalid_range")

    logger.info(
        "JJC flat-members request start: timestamp={} range={} limit={}".format(
            timestamp,
            range_key,
            limit,
        )
    )
    result = await JjcRankingStatsRepo().list_flat_members(
        int(timestamp),
        range_key,
        limit=limit,
    )
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "JJC flat-members request done: timestamp={} range={} limit={} elapsed_ms={} item_count={} total={} detail_count={}".format(
            timestamp,
            range_key,
            limit,
            elapsed_ms,
            result.get("item_count"),
            result.get("total"),
            result.get("detail_count"),
        )
    )
    if not result.get("items"):
        return error_response("not_found", data=result)
    return success_response(result)


@router.get("/ranking-stats/peak-score")
async def get_jjc_peak_score_ranking(
    timestamp: str = Query(..., description="统计锚点时间戳"),
    score_type: str = Query(..., description="tuilan 或 game"),
    range_key: str = Query("top_1000", alias="range", description="排名范围"),
    version: int = Query(1, ge=1, description="统计口径版本"),
    include_match_summary: bool = Query(True, description="是否补充最高分对局心法摘要"),
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    if not timestamp.isdigit():
        return error_response("invalid_timestamp")
    score_type = score_type.strip().lower()
    if score_type not in {"tuilan", "game"}:
        return error_response("invalid_score_type")
    range_key = range_key.strip()
    limit = _RANGE_LIMITS.get(range_key)
    if limit is None:
        return error_response("invalid_range")

    logger.info(
            "JJC peak-score request start: timestamp={} score_type={} range={} version={} limit={} include_match_summary={}".format(
                timestamp,
                score_type,
                range_key,
                version,
                limit,
                include_match_summary,
            )
    )
    load_started_at = time.perf_counter()
    doc = None
    load_timed_out = False
    try:
        doc = await asyncio.wait_for(
            JjcPeakScoreRankingRepo().load_result(
                anchor_timestamp=int(timestamp),
                score_type=score_type,
                version=version,
                items_limit=limit,
                max_time_ms=1500,
            ),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        load_timed_out = True
    load_elapsed_ms = int((time.perf_counter() - load_started_at) * 1000)
    if not doc:
        logger.info(
            "JJC peak-score cache miss, fallback aggregate: timestamp={} score_type={} range={} version={} load_elapsed_ms={} load_timed_out={}".format(
                timestamp,
                score_type,
                range_key,
                version,
                load_elapsed_ms,
                load_timed_out,
            )
        )
        fallback_started_at = time.perf_counter()
        window_end = int(timestamp)
        window_start = window_end - 7 * 86400
        aggregate = await JjcMatchParticipantRepo().aggregate_peak_scores(
            window_start=window_start,
            window_end=window_end,
            score_type=score_type,
            max_items=limit,
            include_source_counts=False,
        )
        fallback_elapsed_ms = int((time.perf_counter() - fallback_started_at) * 1000)
        doc = {
            "anchor_timestamp": window_end,
            "window_start": window_start,
            "window_end": window_end,
            "score_type": score_type,
            "window_days": 7,
            "version": version,
            "status": "done",
            "items": aggregate.get("items") or [],
            "item_count": int(aggregate.get("item_count") or 0),
            "source_match_count": int(aggregate.get("source_match_count") or 0),
            "source_participant_count": int(aggregate.get("source_participant_count") or 0),
            "fallback_aggregate": True,
            "fallback_elapsed_ms": fallback_elapsed_ms,
        }
    if doc.get("status") != "done":
        logger.info(
            "JJC peak-score request miss: timestamp={} score_type={} range={} version={} load_elapsed_ms={} found={}".format(
                timestamp,
                score_type,
                range_key,
                version,
                load_elapsed_ms,
                bool(doc),
            )
        )
        return error_response("not_found", data=doc or {})

    items = doc.get("items") or []
    if not isinstance(items, list):
        items = []
    payload = dict(doc)
    payload["range"] = range_key
    payload["items"] = items[:limit]
    payload["item_count"] = len(payload["items"])
    payload["total"] = int(doc.get("item_count") or len(items))
    payload["kungfu_statistics"] = _build_peak_kungfu_statistics(payload["items"])

    match_ids = []
    for item in payload["items"]:
        if isinstance(item, dict):
            match_id = item.get("match_id")
            if isinstance(match_id, int):
                match_ids.append(match_id)
    summaries: Dict[int, Dict[str, Any]] = {}
    if include_match_summary and match_ids:
        summary_started_at = time.perf_counter()
        summary_timed_out = False
        try:
            summaries = await asyncio.wait_for(
                JjcInspectRepo().batch_load_cached_detail_summaries(match_ids),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            summary_timed_out = True
            summaries = {}
        summary_elapsed_ms = int((time.perf_counter() - summary_started_at) * 1000)
        if summary_timed_out:
            logger.info(
                "JJC peak-score summary load timeout: timestamp={} score_type={} range={} match_ids={} elapsed_ms={}".format(
                    timestamp,
                    score_type,
                    range_key,
                    len(match_ids),
                    summary_elapsed_ms,
                )
            )
        for item in payload["items"]:
            if not isinstance(item, dict):
                continue
            match_id = item.get("match_id")
            if isinstance(match_id, int) and match_id in summaries:
                item["cached_detail_summary"] = summaries[match_id]
    else:
        summary_elapsed_ms = 0
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "JJC peak-score request done: timestamp={} score_type={} range={} version={} include_match_summary={} elapsed_ms={} load_elapsed_ms={} summary_elapsed_ms={} item_count={} total={} match_ids={} summaries={}".format(
            timestamp,
            score_type,
            range_key,
            version,
            include_match_summary,
            elapsed_ms,
            load_elapsed_ms,
            summary_elapsed_ms,
            payload["item_count"],
            payload["total"],
            len(match_ids),
            len(summaries) if match_ids else 0,
        )
    )
    return success_response(payload)


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
    identity_only: bool = Query(False, description="是否只从本地 role_identities 解析身份"),
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
        identity_only=identity_only,
    )
    if result.get("error"):
        return error_response(result.get("message") or result.get("error") or "unknown_error", data=result)
    return success_response(result)


@router.get("/ranking-stats/synced-role")
async def get_ranking_stats_synced_role(
    server: str = Query("", description="服务器名；为空时返回全服候选"),
    name: str = Query(..., description="角色名"),
) -> dict[str, Any]:
    server = server.strip()
    name = name.strip()
    if not name:
        return error_response("invalid_params")

    result = await jjc_ranking_inspect_service.resolve_synced_role(server=server, name=name)
    if result.get("error"):
        return error_response(result.get("message") or "unknown_error", data=result)
    return success_response(result)


@router.get("/ranking-stats/synced-role-matches")
async def get_ranking_stats_synced_role_matches(
    server: str = Query(..., description="服务器名"),
    name: str = Query(..., description="角色名"),
    page: int = Query(1, ge=1, description="分页页码"),
    page_size: int = Query(20, ge=1, le=100, description="分页大小"),
) -> dict[str, Any]:
    started_at = time.perf_counter()
    server = server.strip()
    name = name.strip()
    if not server or not name:
        return error_response("invalid_params")

    result = await jjc_ranking_inspect_service.get_synced_role_matches(
        server=server,
        name=name,
        page=page,
        page_size=page_size,
    )
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "JJC 对局查询 API 完成: endpoint=synced-role-matches server={} name={} page={} page_size={} "
        "elapsed_ms={} error={} total={} items={}".format(
            server,
            name,
            page,
            page_size,
            elapsed_ms,
            bool(result.get("error")),
            ((result.get("pagination") or {}).get("total") if isinstance(result.get("pagination"), dict) else None),
            len(result.get("recent_matches") or []) if isinstance(result.get("recent_matches"), list) else None,
        )
    )
    if result.get("error"):
        return error_response(result.get("message") or "unknown_error", data=result)
    return success_response(result)


@router.post("/ranking-stats/synced-role-sync")
async def post_ranking_stats_synced_role_sync(
    payload: Optional[Dict[str, Any]] = Body(None),
    server: Optional[str] = Query(None, description="服务器名"),
    name: Optional[str] = Query(None, description="角色名"),
) -> dict[str, Any]:
    body = payload or {}
    server_text = (server or body.get("server") or "").strip()
    name_text = (name or body.get("name") or "").strip()
    if not server_text or not name_text:
        return error_response("invalid_params")

    result = await jjc_ranking_inspect_service.enqueue_synced_role(
        server=server_text,
        name=name_text,
    )
    if result.get("error"):
        return error_response(result.get("message") or "unknown_error", data=result)
    return success_response(result)


@router.get("/ranking-stats/match-detail")
async def get_ranking_stats_match_detail(
    match_id: str = Query(..., description="对局 ID"),
) -> dict[str, Any]:
    started_at = time.perf_counter()
    result = await jjc_ranking_inspect_service.get_match_detail(match_id=match_id)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    cache = result.get("cache") if isinstance(result, dict) else None
    logger.info(
        "JJC 对局查询 API 完成: endpoint=match-detail match_id={} elapsed_ms={} error={} cache_hit={}".format(
            match_id,
            elapsed_ms,
            bool(result.get("error")) if isinstance(result, dict) else None,
            cache.get("hit") if isinstance(cache, dict) else None,
        )
    )
    if result.get("error"):
        return error_response(result.get("message") or result.get("error") or "unknown_error", data=result)
    return success_response(result)
