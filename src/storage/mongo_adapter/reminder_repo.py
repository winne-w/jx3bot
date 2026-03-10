from __future__ import annotations

from typing import Any

from nonebot import logger

from src.storage.mongo_adapter.base import MongoProvider


class MongoReminderRepo:
    def __init__(self, provider: MongoProvider) -> None:
        self._provider = provider

    def load_grouped(self) -> dict[str, list[dict[str, Any]]]:
        collection = self._provider.collection("group_reminders")
        if collection is None:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        try:
            cursor = collection.find({}).sort([("group_id", 1), ("remind_at_ts", 1), ("created_at", 1)])
            for document in cursor:
                item = _normalize_reminder_document(document)
                group_id = item.get("group_id", "")
                grouped.setdefault(group_id, []).append(item)
        except Exception as exc:
            logger.warning(f"读取 Mongo group_reminders 失败: {exc}")
            return {}
        return grouped

    def create(self, reminder: dict[str, Any]) -> None:
        collection = self._provider.collection("group_reminders")
        if collection is None:
            return
        document = {
            "_id": reminder["id"],
            **reminder,
            "remind_at_ts": _parse_remind_at_ts(reminder.get("remind_at", "")),
        }
        try:
            collection.replace_one({"_id": document["_id"]}, document, upsert=True)
        except Exception as exc:
            logger.warning(f"写入 Mongo group_reminders 失败: reminder_id={reminder.get('id')} error={exc}")

    def list_pending_by_group(self, group_id: str) -> list[dict[str, Any]]:
        collection = self._provider.collection("group_reminders")
        if collection is None:
            return []
        try:
            cursor = collection.find({"group_id": str(group_id), "status": "pending"}).sort(
                [("remind_at_ts", 1), ("created_at", 1)]
            )
            return [_normalize_reminder_document(item) for item in cursor]
        except Exception as exc:
            logger.warning(f"读取 Mongo group_reminders 失败: group_id={group_id} error={exc}")
            return []

    def list_pending_by_user(self, group_id: str, user_id: str) -> list[dict[str, Any]]:
        collection = self._provider.collection("group_reminders")
        if collection is None:
            return []
        try:
            cursor = collection.find(
                {
                    "group_id": str(group_id),
                    "creator_user_id": str(user_id),
                    "status": "pending",
                }
            ).sort([("remind_at_ts", 1), ("created_at", 1)])
            return [_normalize_reminder_document(item) for item in cursor]
        except Exception as exc:
            logger.warning(
                f"读取 Mongo group_reminders 失败: group_id={group_id} user_id={user_id} error={exc}"
            )
            return []

    def update_pending(self, reminder_id: str, updates: dict[str, Any]) -> bool:
        collection = self._provider.collection("group_reminders")
        if collection is None:
            return False
        update_doc = dict(updates)
        if "remind_at" in update_doc:
            update_doc["remind_at_ts"] = _parse_remind_at_ts(str(update_doc["remind_at"]))
        try:
            result = collection.update_one(
                {"_id": reminder_id, "status": "pending"},
                {"$set": update_doc},
            )
            return bool(result.modified_count)
        except Exception as exc:
            logger.warning(f"更新 Mongo group_reminders 失败: reminder_id={reminder_id} error={exc}")
            return False

    def find_pending(self, reminder_id: str) -> dict[str, Any] | None:
        collection = self._provider.collection("group_reminders")
        if collection is None:
            return None
        try:
            document = collection.find_one({"_id": reminder_id, "status": "pending"})
        except Exception as exc:
            logger.warning(f"读取 Mongo group_reminders 失败: reminder_id={reminder_id} error={exc}")
            return None
        if not isinstance(document, dict):
            return None
        return _normalize_reminder_document(document)


def _parse_remind_at_ts(value: str) -> int | None:
    from datetime import datetime

    normalized = (value or "").strip()
    if len(normalized) == 12:
        normalized = f"{normalized}00"
    try:
        return int(datetime.strptime(normalized, "%Y%m%d%H%M%S").timestamp())
    except ValueError:
        return None


def _normalize_reminder_document(document: dict[str, Any]) -> dict[str, Any]:
    item = dict(document)
    item["id"] = str(item.pop("_id"))
    item.pop("remind_at_ts", None)
    return item
