from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger


@dataclass(frozen=True)
class StatusCacheRepo:
    db: AsyncIOMotorDatabase

    async def load(self, cache_name: str, default: Any = None) -> Any:
        doc = await self.db.status_cache.find_one({"cache_name": cache_name})
        if doc is None:
            return default
        return doc.get("data", default)

    async def save(self, cache_name: str, data: Any) -> None:
        await self.db.status_cache.update_one(
            {"cache_name": cache_name},
            {"$set": {"data": data, "updated_at": int(time.time())}},
            upsert=True,
        )
