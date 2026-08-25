from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


def _strip_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


def _to_snapshot_metadata(doc: Dict[str, Any]) -> Dict[str, Any]:
    week_info = str(doc.get("week_info") or "")
    is_settlement = "结算" in week_info
    return {
        "timestamp": doc["timestamp"],
        "generated_at": doc.get("generated_at"),
        "ranking_cache_time": doc.get("ranking_cache_time"),
        "default_week": doc.get("default_week"),
        "current_season": doc.get("current_season"),
        "week_info": doc.get("week_info"),
        "is_settlement": is_settlement,
        "snapshot_kind": "settlement" if is_settlement else "daily",
    }


def _normalize_season(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class JjcRankingStatsRepo:
    db: Optional[AsyncIOMotorDatabase] = None
    suppress_errors: bool = True

    def _handle_error(self, message: str, exc: Exception) -> None:
        logger.warning(message)
        if not self.suppress_errors:
            raise exc

    # ------------------------------------------------------------------
    # save_snapshot – batch upsert entry point for service code
    # ------------------------------------------------------------------

    async def save_snapshot(
        self,
        timestamp: int,
        summary_payload: Dict[str, Any],
        detail_payloads: List[Dict[str, Any]],
        source: str = "ranking_job",
    ) -> None:
        await self.upsert_summary(timestamp, summary_payload, source=source)
        for detail in detail_payloads:
            await self.upsert_detail(
                timestamp,
                detail["range"],
                detail["lane"],
                detail["kungfu"],
                detail.get("members", []),
                source=source,
            )

    # ------------------------------------------------------------------
    # upsert helpers – usable by migration scripts too
    # ------------------------------------------------------------------

    async def upsert_summary(
        self,
        timestamp: int,
        payload: Dict[str, Any],
        source: str = "ranking_job",
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        doc = {
            "timestamp": timestamp,
            "generated_at": payload.get("generated_at"),
            "ranking_cache_time": payload.get("ranking_cache_time"),
            "default_week": payload.get("default_week"),
            "current_season": payload.get("current_season"),
            "week_info": payload.get("week_info"),
            "kungfu_statistics": payload.get("kungfu_statistics", {}),
            "source": source,
            "schema_version": 1,
            "updated_at": now,
        }
        try:
            db = self.db if self.db is not None else _get_db()
            await db.jjc_ranking_stat_summaries.update_one(
                {"timestamp": timestamp},
                {"$set": doc, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except Exception as exc:
            self._handle_error(
                "upsert jjc_ranking_stat_summaries 失败: timestamp={} error={}".format(
                    timestamp,
                    exc,
                ),
                exc,
            )

    async def upsert_detail(
        self,
        timestamp: int,
        range_key: str,
        lane: str,
        kungfu: str,
        members: List[Dict[str, Any]],
        source: str = "ranking_job",
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        doc = {
            "timestamp": timestamp,
            "range": range_key,
            "lane": lane,
            "kungfu": kungfu,
            "members": members,
            "source": source,
            "schema_version": 1,
            "updated_at": now,
        }
        try:
            db = self.db if self.db is not None else _get_db()
            await db.jjc_ranking_stat_details.update_one(
                {"timestamp": timestamp, "range": range_key, "lane": lane, "kungfu": kungfu},
                {"$set": doc, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except Exception as exc:
            self._handle_error(
                "upsert jjc_ranking_stat_details 失败: "
                "timestamp={} range={} lane={} kungfu={} error={}".format(
                    timestamp,
                    range_key,
                    lane,
                    kungfu,
                    exc,
                ),
                exc,
            )

    # ------------------------------------------------------------------
    # load methods
    # ------------------------------------------------------------------

    async def load_summary(self, timestamp: int) -> Optional[Dict[str, Any]]:
        try:
            db = self.db if self.db is not None else _get_db()
            doc = await db.jjc_ranking_stat_summaries.find_one({"timestamp": timestamp})
            return _strip_id(doc)
        except Exception as exc:
            self._handle_error(
                "load jjc_ranking_stat_summaries 失败: timestamp={} error={}".format(
                    timestamp,
                    exc,
                ),
                exc,
            )
            return None

    async def load_detail(
        self,
        timestamp: int,
        range_key: str,
        lane: str,
        kungfu: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            db = self.db if self.db is not None else _get_db()
            doc = await db.jjc_ranking_stat_details.find_one(
                {
                    "timestamp": timestamp,
                    "range": range_key,
                    "lane": lane,
                    "kungfu": kungfu,
                }
            )
            return _strip_id(doc)
        except Exception as exc:
            self._handle_error(
                "load jjc_ranking_stat_details 失败: "
                "timestamp={} range={} lane={} kungfu={} error={}".format(
                    timestamp,
                    range_key,
                    lane,
                    kungfu,
                    exc,
                ),
                exc,
            )
            return None

    async def list_flat_members(
        self,
        timestamp: int,
        range_key: str,
        *,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        safe_limit = max(0, int(limit or 0))
        started_at = time.perf_counter()
        try:
            db = self.db if self.db is not None else _get_db()
            detail_query = {"timestamp": timestamp, "range": range_key}
            detail_count = 0
            count_documents = getattr(db.jjc_ranking_stat_details, "count_documents", None)
            if callable(count_documents):
                try:
                    detail_count = int(await count_documents(detail_query))
                except Exception:
                    detail_count = 0
            items: List[Dict[str, Any]] = []
            total = 0

            try:
                aggregate_started_at = time.perf_counter()
                items_pipeline = [
                    {"$project": {"_id": 0, "lane": 1, "kungfu": 1, "members": 1}},
                    {"$unwind": "$members"},
                    {
                        "$replaceRoot": {
                            "newRoot": {
                                "$mergeObjects": [
                                    "$members",
                                    {
                                        "lane": "$lane",
                                        "kungfu": "$kungfu",
                                    },
                                ]
                            }
                        }
                    },
                    {
                        "$sort": {
                            "rank": 1,
                            "server": 1,
                            "name": 1,
                        }
                    },
                ]
                if safe_limit:
                    items_pipeline.append({"$limit": safe_limit})

                cursor = db.jjc_ranking_stat_details.aggregate(
                    [
                        {"$match": detail_query},
                        {
                            "$facet": {
                                "items": items_pipeline,
                                "total": [
                                    {"$project": {"_id": 0, "members": 1}},
                                    {"$unwind": "$members"},
                                    {"$count": "value"},
                                ],
                            }
                        },
                    ],
                    allowDiskUse=True,
                )
                docs = await cursor.to_list(length=1)
                facet_doc = docs[0] if docs else {}
                raw_items = facet_doc.get("items") or []
                if isinstance(raw_items, list):
                    for doc in raw_items:
                        if isinstance(doc, dict):
                            items.append(doc)
                total_docs = facet_doc.get("total") or []
                if isinstance(total_docs, list) and total_docs:
                    total = int(total_docs[0].get("value") or 0)
                else:
                    total = len(items)
                aggregate_elapsed_ms = int((time.perf_counter() - aggregate_started_at) * 1000)
                logger.info(
                    "JJC flat-members aggregate done: timestamp={} range={} limit={} detail_count={} total={} item_count={} elapsed_ms={}".format(
                        timestamp,
                        range_key,
                        safe_limit,
                        detail_count,
                        total,
                        len(items),
                        aggregate_elapsed_ms,
                    )
                )
            except Exception:
                fallback_started_at = time.perf_counter()
                cursor = db.jjc_ranking_stat_details.find(
                    detail_query,
                    {"_id": 0, "lane": 1, "kungfu": 1, "members": 1},
                )
                async for doc in cursor:
                    lane = doc.get("lane")
                    detail_kungfu = doc.get("kungfu")
                    members = doc.get("members") or []
                    if not isinstance(members, list):
                        continue
                    for member in members:
                        if not isinstance(member, dict):
                            continue
                        item = dict(member)
                        item["lane"] = item.get("lane") or lane
                        item["kungfu"] = item.get("kungfu") or detail_kungfu
                        items.append(item)

                def rank_key(item: Dict[str, Any]) -> Any:
                    rank = item.get("rank")
                    try:
                        return int(rank)
                    except (TypeError, ValueError):
                        return 999999

                items.sort(key=lambda item: (rank_key(item), str(item.get("server") or ""), str(item.get("name") or "")))
                total = len(items)
                if safe_limit:
                    items = items[:safe_limit]
                fallback_elapsed_ms = int((time.perf_counter() - fallback_started_at) * 1000)
                logger.info(
                    "JJC flat-members fallback done: timestamp={} range={} limit={} detail_count={} total={} item_count={} elapsed_ms={}".format(
                        timestamp,
                        range_key,
                        safe_limit,
                        detail_count,
                        total,
                        len(items),
                        fallback_elapsed_ms,
                    )
                )
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "JJC flat-members request done: timestamp={} range={} limit={} elapsed_ms={} total={} item_count={} detail_count={}".format(
                    timestamp,
                    range_key,
                    safe_limit,
                    elapsed_ms,
                    total,
                    len(items),
                    detail_count,
                )
            )
            return {
                "timestamp": timestamp,
                "range": range_key,
                "items": items,
                "item_count": len(items),
                "total": total,
                "detail_count": detail_count,
            }
        except Exception as exc:
            self._handle_error(
                "list jjc_ranking_stat_details flat members 失败: timestamp={} range={} error={}".format(
                    timestamp,
                    range_key,
                    exc,
                ),
                exc,
            )
            return {
                "timestamp": timestamp,
                "range": range_key,
                "items": [],
                "item_count": 0,
                "total": 0,
                "detail_count": 0,
            }

    # ------------------------------------------------------------------
    # list timestamps
    # ------------------------------------------------------------------

    async def list_seasons(self) -> Dict[str, Any]:
        try:
            db = self.db if self.db is not None else _get_db()
            cursor = db.jjc_ranking_stat_summaries.find(
                {},
                {"current_season": 1, "timestamp": 1},
            ).sort([("timestamp", -1)])
            latest_timestamps: Dict[str, int] = {}
            async for doc in cursor:
                season = _normalize_season(doc.get("current_season"))
                timestamp = int(doc.get("timestamp") or 0)
                if season and timestamp > latest_timestamps.get(season, 0):
                    latest_timestamps[season] = timestamp
            seasons = [
                {"name": name, "latest_timestamp": timestamp}
                for name, timestamp in latest_timestamps.items()
            ]
            seasons.sort(key=lambda item: item["latest_timestamp"], reverse=True)
            return {
                "seasons": seasons,
                "default_season": seasons[0]["name"] if seasons else None,
            }
        except Exception as exc:
            self._handle_error("list jjc ranking seasons 失败: error={}".format(exc), exc)
            return {"seasons": [], "default_season": None}

    async def list_season_history(self, season: str) -> Dict[str, Any]:
        season = str(season or "").strip()
        if not season:
            return {"season": season, "items": [], "total": 0}
        try:
            db = self.db if self.db is not None else _get_db()
            season_values: List[Any] = [season]
            try:
                numeric_season = int(season)
            except ValueError:
                numeric_season = None
            if numeric_season is not None and str(numeric_season) == season:
                season_values.append(numeric_season)
            projection = {
                "timestamp": 1,
                "generated_at": 1,
                "ranking_cache_time": 1,
                "default_week": 1,
                "current_season": 1,
                "week_info": 1,
            }
            cursor = db.jjc_ranking_stat_summaries.find(
                {"current_season": {"$in": season_values}}, projection
            ).sort([("timestamp", -1)])
            items: List[Dict[str, Any]] = []
            async for doc in cursor:
                if "timestamp" in doc:
                    items.append(_to_snapshot_metadata(doc))
            return {"season": season, "items": items, "total": len(items)}
        except Exception as exc:
            self._handle_error(
                "list jjc ranking season history 失败: season={} error={}".format(season, exc),
                exc,
            )
            return {"season": season, "items": [], "total": 0}

    async def list_timestamps(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        with_meta: bool = False,
    ) -> Any:
        sort_order = [("timestamp", -1)]

        if with_meta:
            is_paged = True
            normalized_page = max(int(page or 1), 1)
            normalized_page_size = max(min(int(page_size or 100), 100), 1)
        else:
            is_paged = page is not None or page_size is not None

        try:
            db = self.db if self.db is not None else _get_db()

            if with_meta:
                normalized_page = max(int(page or 1), 1)
                normalized_page_size = max(min(int(page_size or 100), 100), 1)
                total = await db.jjc_ranking_stat_summaries.count_documents({})
                skip = max(0, (normalized_page - 1) * normalized_page_size)
                projection = {
                    "timestamp": 1,
                    "generated_at": 1,
                    "ranking_cache_time": 1,
                    "default_week": 1,
                    "current_season": 1,
                    "week_info": 1,
                }
                cursor = (
                    db.jjc_ranking_stat_summaries.find({}, projection)
                    .sort(sort_order)
                    .skip(skip)
                    .limit(normalized_page_size)
                )
                items: List[Dict[str, Any]] = []
                async for doc in cursor:
                    items.append(_to_snapshot_metadata(doc))
                has_more = (skip + normalized_page_size) < total
                return {
                    "items": items,
                    "page": normalized_page,
                    "page_size": normalized_page_size,
                    "total": total,
                    "has_more": has_more,
                }

            if not is_paged:
                cursor = db.jjc_ranking_stat_summaries.find(
                    {}, {"timestamp": 1}
                ).sort(sort_order)
                result: List[int] = []
                async for doc in cursor:
                    result.append(doc["timestamp"])
                return result

            normalized_page = max(int(page or 1), 1)
            normalized_page_size = max(min(int(page_size or 20), 100), 1)
            total = await db.jjc_ranking_stat_summaries.count_documents({})
            skip = max(0, (normalized_page - 1) * normalized_page_size)
            cursor = (
                db.jjc_ranking_stat_summaries.find({}, {"timestamp": 1})
                .sort(sort_order)
                .skip(skip)
                .limit(normalized_page_size)
            )
            items: List[int] = []
            async for doc in cursor:
                items.append(doc["timestamp"])
            has_more = (skip + normalized_page_size) < total
            return {
                "items": items,
                "page": normalized_page,
                "page_size": normalized_page_size,
                "total": total,
                "has_more": has_more,
            }
        except Exception as exc:
            self._handle_error(
                "list jjc_ranking_stat_summaries 失败: error={}".format(exc),
                exc,
            )
            if with_meta:
                return {
                    "items": [],
                    "page": page or 1,
                    "page_size": page_size or 100,
                    "total": 0,
                    "has_more": False,
                }
            if not is_paged:
                return []
            return {
                "items": [],
                "page": page or 1,
                "page_size": page_size or 20,
                "total": 0,
                "has_more": False,
            }
