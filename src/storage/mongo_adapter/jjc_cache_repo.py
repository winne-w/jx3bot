from __future__ import annotations

from datetime import timedelta
from typing import Any

from nonebot import logger

from src.storage.mongo_adapter.base import MongoProvider, utcnow


class MongoJjcCacheRepo:
    def __init__(self, provider: MongoProvider) -> None:
        self._provider = provider

    def load_ranking_cache(self) -> dict[str, Any] | None:
        collection = self._provider.collection("jjc_ranking_cache")
        if collection is None:
            return None
        try:
            document = collection.find_one({"_id": "current"})
        except Exception as exc:
            logger.warning(f"读取 Mongo jjc_ranking_cache 失败: {exc}")
            return None
        if not isinstance(document, dict):
            return None
        expires_at = document.get("expires_at")
        if expires_at and expires_at <= utcnow():
            return None
        data = document.get("data")
        return data if isinstance(data, dict) else None

    def save_ranking_cache(self, ranking_result: dict[str, Any], *, ttl_seconds: int) -> None:
        collection = self._provider.collection("jjc_ranking_cache")
        if collection is None:
            return
        cache_time = float(ranking_result.get("cache_time") or 0)
        now = utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        if cache_time:
            expires_at = datetime_from_timestamp(cache_time) + timedelta(seconds=ttl_seconds)
        document = {
            "_id": "current",
            "cache_time": cache_time,
            "data": ranking_result,
            "expires_at": expires_at,
            "updated_at": now,
        }
        try:
            collection.replace_one({"_id": "current"}, document, upsert=True)
        except Exception as exc:
            logger.warning(f"写入 Mongo jjc_ranking_cache 失败: {exc}")

    def load_kungfu_cache(self, server: str, name: str, *, allow_expired: bool = False) -> dict[str, Any] | None:
        collection = self._provider.collection("jjc_kungfu_cache")
        if collection is None:
            return None
        try:
            document = collection.find_one({"_id": f"{server}:{name}"})
        except Exception as exc:
            logger.warning(f"读取 Mongo jjc_kungfu_cache 失败: server={server} name={name} error={exc}")
            return None
        if not isinstance(document, dict):
            return None
        expires_at = document.get("expires_at")
        if not allow_expired and expires_at and expires_at <= utcnow():
            return None
        document.pop("_id", None)
        document.pop("updated_at", None)
        document.pop("expires_at", None)
        return document

    def save_kungfu_cache(
        self,
        server: str,
        name: str,
        result: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        collection = self._provider.collection("jjc_kungfu_cache")
        if collection is None:
            return
        cache_time = float(result.get("cache_time") or 0)
        now = utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        if cache_time:
            expires_at = datetime_from_timestamp(cache_time) + timedelta(seconds=ttl_seconds)
        document = {
            "_id": f"{server}:{name}",
            "server": server,
            "name": name,
            **result,
            "updated_at": now,
            "expires_at": expires_at,
        }
        try:
            collection.replace_one({"_id": document["_id"]}, document, upsert=True)
        except Exception as exc:
            logger.warning(f"写入 Mongo jjc_kungfu_cache 失败: server={server} name={name} error={exc}")


def datetime_from_timestamp(value: float):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, tz=timezone.utc)
