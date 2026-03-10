from __future__ import annotations

from datetime import datetime
from typing import Any

from nonebot import logger

from src.storage.mongo_adapter.base import MongoProvider, utcnow


class MongoCacheEntryRepo:
    def __init__(self, provider: MongoProvider) -> None:
        self._provider = provider

    def get_payload(self, namespace: str, key: str) -> Any | None:
        collection = self._provider.collection("cache_entries")
        if collection is None:
            return None
        try:
            document = collection.find_one({"namespace": namespace, "key": key})
        except Exception as exc:
            logger.warning(f"读取 Mongo cache_entries 失败: namespace={namespace} key={key} error={exc}")
            return None
        if not isinstance(document, dict):
            return None
        expires_at = document.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= utcnow():
            return None
        return document.get("payload")

    def upsert_payload(
        self,
        namespace: str,
        key: str,
        payload: Any,
        *,
        expires_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        collection = self._provider.collection("cache_entries")
        if collection is None:
            return
        document = {
            "_id": f"{namespace}:{key}",
            "namespace": namespace,
            "key": key,
            "payload": payload,
            "version": 1,
            "updated_at": utcnow(),
            "expires_at": expires_at,
            "meta": meta or {},
        }
        try:
            collection.replace_one({"_id": document["_id"]}, document, upsert=True)
        except Exception as exc:
            logger.warning(f"写入 Mongo cache_entries 失败: namespace={namespace} key={key} error={exc}")
