from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


COLLECTION_NAME = "jjc_peak_score_rankings"


def _strip_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


@dataclass(frozen=True)
class JjcPeakScoreRankingRepo:
    db: Optional[AsyncIOMotorDatabase] = None
    suppress_errors: bool = True

    COLLECTION_NAME = COLLECTION_NAME

    def _db(self) -> AsyncIOMotorDatabase:
        return self.db if self.db is not None else _get_db()

    def _handle_error(self, message: str, exc: Exception) -> None:
        logger.warning(message)
        if not self.suppress_errors:
            raise exc

    @staticmethod
    def _key(anchor_timestamp: int, score_type: str, version: int) -> Dict[str, Any]:
        return {
            "anchor_timestamp": int(anchor_timestamp),
            "score_type": score_type,
            "version": int(version),
        }

    async def load_result(
        self,
        *,
        anchor_timestamp: int,
        score_type: str,
        version: int = 1,
    ) -> Optional[Dict[str, Any]]:
        try:
            doc = await self._db().jjc_peak_score_rankings.find_one(
                self._key(anchor_timestamp, score_type, version)
            )
            return _strip_id(doc)
        except Exception as exc:
            self._handle_error(
                "读取 JJC 最高分排名失败: anchor={} score_type={} version={} error={}".format(
                    anchor_timestamp,
                    score_type,
                    version,
                    exc,
                ),
                exc,
            )
            return None

    async def is_done(
        self,
        *,
        anchor_timestamp: int,
        score_type: str,
        version: int = 1,
    ) -> bool:
        doc = await self.load_result(
            anchor_timestamp=anchor_timestamp,
            score_type=score_type,
            version=version,
        )
        return bool(doc and doc.get("status") == "done")

    async def mark_processing(
        self,
        *,
        anchor_timestamp: int,
        score_type: str,
        window_start: int,
        window_end: int,
        window_days: int = 7,
        version: int = 1,
    ) -> None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now = time.time()
        doc = {
            "anchor_timestamp": int(anchor_timestamp),
            "score_type": score_type,
            "window_start": int(window_start),
            "window_end": int(window_end),
            "window_days": int(window_days),
            "version": int(version),
            "status": "processing",
            "error": None,
            "updated_at": now_dt,
            "processing_at": now,
        }
        try:
            await self._db().jjc_peak_score_rankings.update_one(
                self._key(anchor_timestamp, score_type, version),
                {"$set": doc, "$setOnInsert": {"created_at": now_dt}},
                upsert=True,
            )
        except Exception as exc:
            self._handle_error(
                "标记 JJC 最高分排名处理中失败: anchor={} score_type={} version={} error={}".format(
                    anchor_timestamp,
                    score_type,
                    version,
                    exc,
                ),
                exc,
            )

    async def save_done(self, result: Dict[str, Any]) -> None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        doc = dict(result)
        doc["status"] = "done"
        doc["error"] = None
        doc["updated_at"] = now_dt
        try:
            await self._db().jjc_peak_score_rankings.update_one(
                self._key(
                    int(doc["anchor_timestamp"]),
                    str(doc["score_type"]),
                    int(doc.get("version") or 1),
                ),
                {"$set": doc, "$setOnInsert": {"created_at": now_dt}},
                upsert=True,
            )
        except Exception as exc:
            self._handle_error(
                "保存 JJC 最高分排名失败: anchor={} score_type={} error={}".format(
                    doc.get("anchor_timestamp"),
                    doc.get("score_type"),
                    exc,
                ),
                exc,
            )

    async def mark_failed(
        self,
        *,
        anchor_timestamp: int,
        score_type: str,
        window_start: int,
        window_end: int,
        error: str,
        window_days: int = 7,
        version: int = 1,
    ) -> None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        doc = {
            "anchor_timestamp": int(anchor_timestamp),
            "score_type": score_type,
            "window_start": int(window_start),
            "window_end": int(window_end),
            "window_days": int(window_days),
            "version": int(version),
            "status": "failed",
            "error": error[:500],
            "updated_at": now_dt,
            "failed_at": time.time(),
        }
        try:
            await self._db().jjc_peak_score_rankings.update_one(
                self._key(anchor_timestamp, score_type, version),
                {"$set": doc, "$setOnInsert": {"created_at": now_dt}},
                upsert=True,
            )
        except Exception as exc:
            self._handle_error(
                "标记 JJC 最高分排名失败状态失败: anchor={} score_type={} version={} error={}".format(
                    anchor_timestamp,
                    score_type,
                    version,
                    exc,
                ),
                exc,
            )
