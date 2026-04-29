from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


@dataclass(frozen=True)
class ReminderRepo:
    db: Optional[AsyncIOMotorDatabase] = None

    async def insert(self, reminder: dict[str, Any]) -> None:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.reminders.insert_one(reminder)
        except Exception as exc:
            logger.warning("插入提醒失败: reminder_id={} error={}", reminder.get("reminder_id"), exc)

    async def find_by_id(self, reminder_id: str) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            return await db.reminders.find_one({"reminder_id": reminder_id})
        except Exception as exc:
            logger.warning("查询提醒失败: reminder_id={} error={}", reminder_id, exc)
            return None

    async def load_all_pending(self) -> dict[str, list[dict[str, Any]]]:
        """返回 {group_id: [pending_reminder_docs]} 用于启动恢复。"""
        db = self.db if self.db is not None else _get_db()
        result: dict[str, list[dict[str, Any]]] = {}
        try:
            docs = await db.reminders.find({"status": "pending"}).to_list(None)
            for doc in docs:
                gid = doc.get("group_id", "")
                result.setdefault(gid, []).append(doc)
        except Exception as exc:
            logger.warning("加载待执行提醒失败: {}", exc)
        return result

    async def load_by_group(self, group_id: int) -> list[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            return await db.reminders.find({"group_id": str(group_id)}).to_list(None)
        except Exception as exc:
            logger.warning("加载群提醒失败: group_id={} error={}", group_id, exc)
            return []

    async def update_status(self, reminder_id: str, status: str, ts_field: str) -> bool:
        db = self.db if self.db is not None else _get_db()
        try:
            result = await db.reminders.update_one(
                {"reminder_id": reminder_id, "status": "pending"},
                {"$set": {"status": status, ts_field: int(time.time())}},
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.warning("更新提醒状态失败: reminder_id={} error={}", reminder_id, exc)
            return False

    async def cancel(self, reminder_id: str, group_id: int, user_id: int) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            return await db.reminders.find_one_and_update(
                {
                    "reminder_id": reminder_id,
                    "group_id": str(group_id),
                    "creator_user_id": str(user_id),
                    "status": "pending",
                },
                {"$set": {"status": "canceled", "canceled_at": int(time.time())}},
            )
        except Exception as exc:
            logger.warning("取消提醒失败: reminder_id={} error={}", reminder_id, exc)
            return None
