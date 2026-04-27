from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger


@dataclass(frozen=True)
class ServerMasterCacheRepo:
    db: AsyncIOMotorDatabase
    ttl_seconds: int = field(default=7 * 24 * 60 * 60)  # 7 天

    async def get(self, key: str) -> dict[str, Any] | None:
        doc = await self.db.server_master_cache.find_one({"key": key})
        if doc is None:
            return None

        logger.info("[server_master_repo] MongoDB 查询结果: key={} doc_keys={}", key, list(doc.keys()) if doc else None)
        cached_at = int(doc.get("cached_at", 0) or 0)
        now = int(time.time())
        if now - cached_at >= self.ttl_seconds:
            await self.db.server_master_cache.delete_one({"key": key})
            logger.info("[server_master_repo] 过期删除: key={} cached_at={} now={} age_s={}", key, cached_at, now, now - cached_at)
            return None

        logger.info("[server_master_repo] 缓存有效: key={} name={} age_s={}", key, doc.get("name"), now - cached_at)
        return {
            "name": doc.get("name", ""),
            "zone": doc.get("zone", ""),
            "id": doc.get("server_id", ""),
        }

    async def put(self, key: str, entry: dict[str, Any]) -> None:
        await self.db.server_master_cache.update_one(
            {"key": key},
            {
                "$set": {
                    "name": entry.get("name", ""),
                    "zone": entry.get("zone", ""),
                    "server_id": entry.get("id", ""),
                    "cached_at": int(time.time()),
                }
            },
            upsert=True,
        )
        logger.info("[server_master_repo] 写入: key={} name={} zone={}", key, entry.get("name"), entry.get("zone"))

    async def delete(self, key: str) -> None:
        await self.db.server_master_cache.delete_one({"key": key})
