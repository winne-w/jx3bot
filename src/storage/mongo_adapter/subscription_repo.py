from __future__ import annotations

from typing import Any

from nonebot import logger

from src.storage.mongo_adapter.base import MongoProvider


class MongoSubscriptionRepo:
    def __init__(self, provider: MongoProvider) -> None:
        self._provider = provider

    def load_grouped_by_user(self) -> dict[str, list[dict[str, Any]]]:
        collection = self._provider.collection("wanbaolou_subscriptions")
        if collection is None:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        try:
            cursor = collection.find({"enabled": {"$ne": False}}).sort(
                [("user_id", 1), ("created_at", 1), ("item_name", 1)]
            )
            for document in cursor:
                item = _normalize_subscription_document(document)
                grouped.setdefault(item["user_id"], []).append(item)
        except Exception as exc:
            logger.warning(f"读取 Mongo wanbaolou_subscriptions 失败: {exc}")
            return {}
        return grouped

    def replace_grouped_by_user(self, subscriptions: dict[str, list[dict[str, Any]]]) -> None:
        collection = self._provider.collection("wanbaolou_subscriptions")
        if collection is None:
            return
        documents: list[dict[str, Any]] = []
        for user_id, items in subscriptions.items():
            for item in items:
                documents.append(_build_subscription_document(user_id, item))
        try:
            collection.delete_many({})
            if documents:
                collection.insert_many(documents, ordered=False)
        except Exception as exc:
            logger.warning(f"写入 Mongo wanbaolou_subscriptions 失败: {exc}")

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        collection = self._provider.collection("wanbaolou_subscriptions")
        if collection is None:
            return []
        items: list[dict[str, Any]] = []
        try:
            cursor = collection.find(
                {"user_id": str(user_id), "enabled": {"$ne": False}}
            ).sort([("created_at", 1), ("item_name", 1)])
            for document in cursor:
                items.append(_normalize_subscription_document(document))
        except Exception as exc:
            logger.warning(f"读取 Mongo wanbaolou_subscriptions 失败: user_id={user_id} error={exc}")
            return []
        return items

    def list_all_grouped_by_user(self) -> dict[str, list[dict[str, Any]]]:
        return self.load_grouped_by_user()

    def add(self, user_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
        collection = self._provider.collection("wanbaolou_subscriptions")
        if collection is None:
            return None
        document = _build_subscription_document(str(user_id), item)
        try:
            collection.replace_one({"_id": document["_id"]}, document, upsert=True)
        except Exception as exc:
            logger.warning(f"写入 Mongo wanbaolou_subscriptions 失败: user_id={user_id} error={exc}")
            return None
        return _normalize_subscription_document(document)

    def remove_by_index(self, user_id: str, index: int) -> dict[str, Any] | None:
        items = self.list_by_user(user_id)
        if index < 1 or index > len(items):
            return None
        target = items[index - 1]
        collection = self._provider.collection("wanbaolou_subscriptions")
        if collection is None:
            return None
        try:
            result = collection.delete_one({"_id": target.get("_id")})
        except Exception as exc:
            logger.warning(f"删除 Mongo wanbaolou_subscriptions 失败: user_id={user_id} error={exc}")
            return None
        if result.deleted_count:
            return target
        return None


def _build_subscription_document(user_id: str, item: dict[str, Any]) -> dict[str, Any]:
    created_at = item.get("created_at")
    group_id = item.get("group_id")
    item_name = str(item.get("item_name", ""))
    identifier = f"{group_id or ''}:{user_id}:{item_name}:{created_at}"
    return {
        "_id": identifier,
        "group_id": str(group_id) if group_id is not None else "",
        "user_id": str(user_id),
        "item_name": item_name,
        "price_threshold": item.get("price_threshold", 0),
        "created_at": created_at,
        "updated_at": item.get("updated_at", created_at),
        "enabled": item.get("enabled", True),
        "source": item.get("source", "legacy_runtime"),
    }


def _normalize_subscription_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_name": document.get("item_name"),
        "price_threshold": document.get("price_threshold", 0),
        "group_id": int(document["group_id"]) if str(document.get("group_id", "")).isdigit() else document.get("group_id"),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
        "enabled": document.get("enabled", True),
        "_id": document.get("_id"),
    }
