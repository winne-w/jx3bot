from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.infra.mongo import get_db as _get_db

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JjcCacheRepo:
    jjc_ranking_cache_duration: int
    kungfu_cache_duration: int
    db: Optional[AsyncIOMotorDatabase] = None

    async def load_ranking_cache(self) -> Optional[dict[str, Any]]:
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
        if time.time() - cache_time >= self.jjc_ranking_cache_duration:
            logger.info("竞技场排行榜缓存已过期 (MongoDB)")
            return None
        logger.info("使用 MongoDB 缓存的竞技场排行榜数据")
        return doc.get("data")

    async def save_ranking_cache(self, ranking_result: dict[str, Any]) -> None:
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

    async def load_kungfu_cache_raw(self, server: str, name: str) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        doc = await db.kungfu_cache.find_one({"server": server, "name": name})
        if doc is None:
            return None
        return dict(doc)

    async def load_kungfu_cache(self, server: str, name: str) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        doc = await db.kungfu_cache.find_one({"server": server, "name": name})
        if doc is None:
            logger.info(f"心法缓存未命中: server={server} name={name} reason=cache_miss")
            return None

        cached_data = dict(doc)
        cache_time = cached_data.get("cache_time", 0)
        kungfu_value = cached_data.get("kungfu")
        weapon_checked = cached_data.get("weapon_checked", False)
        teammates_checked = cached_data.get("teammates_checked", False)
        teammates = cached_data.get("teammates")
        teammates_ok = (
            isinstance(teammates, list)
            and len(teammates) > 0
            and all(isinstance(item, dict) and item.get("kungfu_id") not in (None, "") for item in teammates)
        )

        if kungfu_value not in [None, ""]:
            current_time = time.time()
            cache_age = current_time - cache_time if cache_time else None
            cache_fresh = (
                cache_time
                and cache_age is not None
                and cache_age < self.kungfu_cache_duration
                and weapon_checked
                and teammates_checked
                and teammates_ok
            )
            if cache_fresh:
                logger.info(f"使用心法缓存: server={server} name={name} cache_time={cache_time}")
                return cached_data

            reasons = []
            if not cache_time:
                reasons.append("missing_cache_time")
            elif cache_age is not None and cache_age >= self.kungfu_cache_duration:
                reasons.append("cache_time_expired")
            if not weapon_checked:
                reasons.append("weapon_not_checked")
            if not teammates_checked:
                reasons.append("teammates_not_checked")
            if not teammates_ok:
                reasons.append("teammates_kungfu_id_missing")
            cache_dt = datetime.fromtimestamp(cache_time).strftime("%Y-%m-%d %H:%M:%S") if cache_time else "未知"
            reason_text = ",".join(reasons) if reasons else "unknown"
            logger.info(
                f"心法缓存不命中: server={server} name={name} cache_time={cache_dt} reason={reason_text}"
            )
        else:
            logger.info(f"心法缓存不命中: server={server} name={name} reason=kungfu_empty")

        return None

    async def save_kungfu_cache(self, server: str, name: str, result: dict[str, Any]) -> None:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.kungfu_cache.update_one(
                {"server": server, "name": name},
                {"$set": {**result, "cache_time": result.get("cache_time", time.time())}},
                upsert=True,
            )
            logger.info(f"心法信息已更新缓存到 MongoDB: server={server} name={name}")
        except Exception as exc:
            logger.warning(f"保存心法缓存失败: server={server} name={name} error={exc}")
