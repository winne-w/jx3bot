from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


@dataclass(frozen=True)
class WanbaolouSubRepo:
    db: Optional[AsyncIOMotorDatabase] = None

    async def find_by_user(self, user_id: str) -> list[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            docs = await db.wanbaolou_subscriptions.find(
                {"user_id": user_id, "active": True}
            ).to_list(None)
            return docs
        except Exception as exc:
            logger.warning("查询订阅失败: user_id={} error={}", user_id, exc)
            return []

    async def add(
        self, user_id: str, item_name: str, price_threshold: int, group_id: Optional[int] = None
    ) -> bool:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.wanbaolou_subscriptions.update_one(
                {"user_id": user_id, "item_name": item_name},
                {"$set": {
                    "user_id": user_id,
                    "item_name": item_name,
                    "price_threshold": price_threshold,
                    "group_id": str(group_id) if group_id else None,
                    "created_at": time.time(),
                    "active": True,
                }},
                upsert=True,
            )
            return True
        except Exception as exc:
            logger.warning("添加订阅失败: user_id={} item_name={} error={}", user_id, item_name, exc)
            return False

    async def remove(self, user_id: str, item_name: str) -> bool:
        db = self.db if self.db is not None else _get_db()
        try:
            result = await db.wanbaolou_subscriptions.update_one(
                {"user_id": user_id, "item_name": item_name, "active": True},
                {"$set": {"active": False}},
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.warning("删除订阅失败: user_id={} item_name={} error={}", user_id, item_name, exc)
            return False

    async def all(self) -> list[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            return await db.wanbaolou_subscriptions.find({"active": True}).to_list(None)
        except Exception as exc:
            logger.warning("查询所有订阅失败: {}", exc)
            return []
