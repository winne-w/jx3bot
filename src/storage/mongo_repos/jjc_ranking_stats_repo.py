from __future__ import annotations

import datetime
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

    # ------------------------------------------------------------------
    # list timestamps
    # ------------------------------------------------------------------

    async def list_timestamps(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Any:
        sort_order = [("timestamp", -1)]

        is_paged = page is not None or page_size is not None

        try:
            db = self.db if self.db is not None else _get_db()
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
            if not is_paged:
                return []
            return {
                "items": [],
                "page": page or 1,
                "page_size": page_size or 20,
                "total": 0,
                "has_more": False,
            }
