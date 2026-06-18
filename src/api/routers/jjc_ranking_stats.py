from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Query
from nonebot import logger

from src.api.response import error_response, success_response
from src.services.jx3.singletons import jjc_ranking_inspect_service
from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo


router = APIRouter(prefix="/api/jjc", tags=["jjc"])


_RANGE_LIMITS = {
    "top_1000": 1000,
    "top_200": 200,
    "top_100": 100,
    "top_50": 50,
}


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
    if not timestamp.isdigit():
        return error_response("invalid_timestamp")
    range_key = range_key.strip()
    limit = _RANGE_LIMITS.get(range_key)
    if limit is None:
        return error_response("invalid_range")

    result = await JjcRankingStatsRepo().list_flat_members(
        int(timestamp),
        range_key,
        limit=limit,
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
) -> Dict[str, Any]:
    if not timestamp.isdigit():
        return error_response("invalid_timestamp")
    score_type = score_type.strip().lower()
    if score_type not in {"tuilan", "game"}:
        return error_response("invalid_score_type")
    range_key = range_key.strip()
    limit = _RANGE_LIMITS.get(range_key)
    if limit is None:
        return error_response("invalid_range")

    doc = await JjcPeakScoreRankingRepo().load_result(
        anchor_timestamp=int(timestamp),
        score_type=score_type,
        version=version,
    )
    if not doc or doc.get("status") != "done":
        return error_response("not_found", data=doc or {})

    items = doc.get("items") or []
    if not isinstance(items, list):
        items = []
    payload = dict(doc)
    payload["range"] = range_key
    payload["items"] = items[:limit]
    payload["item_count"] = len(payload["items"])
    payload["total"] = len(items)
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
