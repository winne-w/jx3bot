from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nonebot import logger

from src.storage.factory import MongoSettings

try:
    from pymongo import ASCENDING, DESCENDING, MongoClient
    from pymongo.collection import Collection
    from pymongo.database import Database
except Exception:  # pragma: no cover
    ASCENDING = 1
    DESCENDING = -1
    MongoClient = None  # type: ignore
    Collection = Any  # type: ignore
    Database = Any  # type: ignore


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MongoProvider:
    def __init__(self, settings: MongoSettings) -> None:
        self._settings = settings
        self._client: MongoClient | None = None
        self._database: Database | None = None
        self._indexes_ready = False

    @property
    def enabled(self) -> bool:
        return bool(self._settings.enabled and MongoClient is not None)

    def database(self) -> Database | None:
        if not self.enabled:
            return None
        if self._database is not None:
            return self._database
        try:
            self._client = MongoClient(self._settings.uri, tz_aware=True, connect=False)
            self._database = self._client[self._settings.database]
            return self._database
        except Exception as exc:
            logger.warning(f"初始化 Mongo 连接失败: {exc}")
            self._database = None
            return None

    def collection(self, name: str) -> Collection | None:
        db = self.database()
        if db is None:
            return None
        self.ensure_indexes()
        return db[name]

    def ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        db = self.database()
        if db is None:
            return
        try:
            db["cache_entries"].create_index(
                [("namespace", ASCENDING), ("key", ASCENDING)],
                unique=True,
                name="uk_namespace_key",
            )
            db["cache_entries"].create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_expires_at",
            )
            db["jjc_ranking_cache"].create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_expires_at",
            )
            db["jjc_kungfu_cache"].create_index(
                [("server", ASCENDING), ("name", ASCENDING)],
                unique=True,
                name="uk_server_name",
            )
            db["jjc_kungfu_cache"].create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_expires_at",
            )
            db["group_reminders"].create_index(
                [("group_id", ASCENDING), ("status", ASCENDING), ("remind_at_ts", ASCENDING)],
                name="idx_group_status_remind_at",
            )
            db["group_reminders"].create_index(
                [("creator_user_id", ASCENDING), ("status", ASCENDING), ("remind_at_ts", ASCENDING)],
                name="idx_creator_status_remind_at",
            )
            db["wanbaolou_subscriptions"].create_index(
                [("group_id", ASCENDING), ("user_id", ASCENDING), ("item_name", ASCENDING), ("created_at", ASCENDING)],
                unique=True,
                name="uk_group_user_item_created",
            )
            db["wanbaolou_subscriptions"].create_index(
                [("user_id", ASCENDING), ("enabled", ASCENDING)],
                name="idx_user_enabled",
            )
            db["wanbaolou_subscriptions"].create_index(
                [("item_name", ASCENDING), ("enabled", ASCENDING)],
                name="idx_item_enabled",
            )
            db["jjc_ranking_stats"].create_index(
                [("generated_at", DESCENDING)],
                name="idx_generated_at_desc",
            )
            self._indexes_ready = True
        except Exception as exc:
            logger.warning(f"初始化 Mongo 索引失败: {exc}")
