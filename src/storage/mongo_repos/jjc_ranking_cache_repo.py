from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.infra.mongo import get_db as _get_db

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from src.utils.jjc_query_observability import foreground_safe_logger

logger = foreground_safe_logger(logger, component="cache")


@dataclass(frozen=True)
class JjcRankingCacheRepo:
    """竞技场排行榜整榜缓存仓储（jjc_ranking_cache）。"""

    db: Optional[AsyncIOMotorDatabase] = None
    cache_duration: int = 3600

    async def load_ranking_cache(self) -> Optional[Dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.jjc_ranking_cache.find_one({"cache_key": "ranking"})
        except Exception as exc:
            logger.warning("读取竞技场排行榜缓存失败: {}", exc)
            return None
        if doc is None:
            logger.info("竞技场排行榜缓存未命中 (MongoDB)")
            return None
        cache_time = doc.get("cache_time", 0)
        if time.time() - cache_time >= self.cache_duration:
            logger.info("竞技场排行榜缓存已过期 (MongoDB)")
            return None
        logger.info("使用 MongoDB 缓存的竞技场排行榜数据")
        return doc.get("data")

    async def save_ranking_cache(self, ranking_result: Dict[str, Any]) -> None:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.jjc_ranking_cache.update_one(
                {"cache_key": "ranking"},
                {"$set": {
                    "cache_time": ranking_result.get("cache_time") or time.time(),
                    "data": ranking_result,
                    "created_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            logger.info("竞技场排行榜数据已保存到 MongoDB 缓存")
        except Exception as exc:
            logger.warning("保存竞技场排行榜缓存失败: {}", exc)
