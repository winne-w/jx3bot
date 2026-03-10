from __future__ import annotations

from typing import Any

from nonebot import logger

from src.storage.mongo_adapter.base import MongoProvider


class MongoJjcRankingStatsRepo:
    def __init__(self, provider: MongoProvider) -> None:
        self._provider = provider

    def list_timestamps(self) -> list[int]:
        collection = self._provider.collection("jjc_ranking_stats")
        if collection is None:
            return []
        try:
            return [int(item["_id"]) for item in collection.find({}, {"_id": 1}).sort([("_id", -1)])]
        except Exception as exc:
            logger.warning(f"读取 Mongo jjc_ranking_stats 列表失败: {exc}")
            return []

    def read(self, timestamp: int) -> dict[str, Any] | None:
        collection = self._provider.collection("jjc_ranking_stats")
        if collection is None:
            return None
        try:
            document = collection.find_one({"_id": int(timestamp)})
        except Exception as exc:
            logger.warning(f"读取 Mongo jjc_ranking_stats 失败: timestamp={timestamp} error={exc}")
            return None
        if not isinstance(document, dict):
            return None
        document.pop("_id", None)
        return document

    def save(self, timestamp: int, payload: dict[str, Any]) -> None:
        collection = self._provider.collection("jjc_ranking_stats")
        if collection is None:
            return
        document = {"_id": int(timestamp), **payload}
        try:
            collection.replace_one({"_id": int(timestamp)}, document, upsert=True)
        except Exception as exc:
            logger.warning(f"写入 Mongo jjc_ranking_stats 失败: timestamp={timestamp} error={exc}")
