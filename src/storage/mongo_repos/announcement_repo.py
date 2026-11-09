from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


@dataclass(frozen=True)
class AnnouncementRepo:
    db: Optional[AsyncIOMotorDatabase] = None

    async def insert(
        self,
        title: str,
        content: str,
        date: str,
        created_by: str,
    ) -> Optional[str]:
        db = self.db if self.db is not None else _get_db()
        announcement_id = uuid.uuid4().hex
        doc = {
            "announcement_id": announcement_id,
            "title": title,
            "content": content,
            "date": date,
            "created_at": time.time(),
            "created_by": created_by,
        }
        try:
            await db.announcements.insert_one(doc)
            return announcement_id
        except Exception as exc:
            logger.warning("插入公告失败: title={} error={}", title, exc)
            return None

    async def find_latest_date_with_announcement(self) -> dict[str, Any]:
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.announcements.find_one(
                {},
                sort=[("date", -1), ("created_at", -1)],
            )
            if doc is None:
                return {"latest_date": None, "announcement": None}
            return {
                "latest_date": doc.get("date"),
                "announcement": {
                    "announcement_id": doc.get("announcement_id"),
                    "title": doc.get("title"),
                    "content": doc.get("content"),
                    "date": doc.get("date"),
                    "created_at": doc.get("created_at"),
                },
            }
        except Exception as exc:
            logger.warning("查询最新公告日期失败: error={}", exc)
            return {"latest_date": None, "announcement": None}

    async def list_paginated(
        self,
        cursor: Optional[float],
        limit: int,
    ) -> dict[str, Any]:
        db = self.db if self.db is not None else _get_db()
        query: dict[str, Any] = {}
        if cursor is not None:
            query["created_at"] = {"$lt": cursor}
        try:
            docs = (
                await db.announcements.find(query)
                .sort("created_at", -1)
                .limit(limit + 1)
                .to_list(limit + 1)
            )
        except Exception as exc:
            logger.warning("分页查询公告失败: error={}", exc)
            return {"announcements": [], "has_more": False, "next_cursor": None}

        has_more = len(docs) > limit
        if has_more:
            docs = docs[:limit]

        announcements = [
            {
                "announcement_id": d.get("announcement_id"),
                "title": d.get("title"),
                "content": d.get("content"),
                "date": d.get("date"),
                "created_at": d.get("created_at"),
            }
            for d in docs
        ]
        next_cursor = announcements[-1]["created_at"] if announcements else None
        return {"announcements": announcements, "has_more": has_more, "next_cursor": next_cursor}

    async def delete_by_id(self, announcement_id: str) -> bool:
        db = self.db if self.db is not None else _get_db()
        try:
            result = await db.announcements.delete_one({"announcement_id": announcement_id})
            return result.deleted_count > 0
        except Exception as exc:
            logger.warning("删除公告失败: announcement_id={} error={}", announcement_id, exc)
            return False
