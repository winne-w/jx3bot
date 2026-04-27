from __future__ import annotations

import asyncio
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from nonebot import logger

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


async def init_mongo(uri: str) -> AsyncIOMotorDatabase:
    global _client, _db
    logger.info("正在连接 MongoDB...")
    _client = AsyncIOMotorClient(uri, maxPoolSize=10, serverSelectionTimeoutMS=5000)
    # 触发连接验证
    await _client.admin.command("ping")
    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    _db = _client[db_name]
    await _ensure_indexes(_db)
    logger.info("MongoDB 连接成功，数据库: {}", db_name)
    return _db


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("MongoDB 未初始化，请先调用 init_mongo()")
    return _db


async def close_mongo() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


async def health_check() -> dict:
    """用于验证 MongoDB 连通性的诊断接口。"""
    import time

    import pymongo

    result = {
        "motor_installed": True,
        "pymongo_version": pymongo.__version__,
        "connected": False,
        "ping_ms": None,
        "collections": [],
        "error": None,
    }

    if _db is None:
        result["error"] = "MongoDB 未初始化"
        return result

    try:
        start = time.monotonic()
        await _db.command("ping")
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        result["connected"] = True
        result["ping_ms"] = elapsed_ms
        result["collections"] = await _db.list_collection_names()
    except Exception as exc:
        result["error"] = str(exc)

    return result


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """幂等创建所有集合的索引。"""
    # server_master_cache
    await db.server_master_cache.create_index("key", unique=True, background=True)
    await db.server_master_cache.create_index(
        "cached_at", expireAfterSeconds=604800, background=True
    )

    # status_cache
    await db.status_cache.create_index("cache_name", unique=True, background=True)

    # kungfu_cache
    await db.kungfu_cache.create_index(
        [("server", 1), ("name", 1)], unique=True, background=True
    )
    await db.kungfu_cache.create_index(
        "cache_time", expireAfterSeconds=604800, background=True
    )

    # jjc_role_recent
    await db.jjc_role_recent.create_index(
        [("server", 1), ("name", 1)], unique=True, background=True
    )
    await db.jjc_role_recent.create_index(
        "cached_at", expireAfterSeconds=600, background=True
    )

    # jjc_match_detail
    await db.jjc_match_detail.create_index("match_id", unique=True, background=True)

    # jjc_ranking_cache
    await db.jjc_ranking_cache.create_index("cache_key", unique=True, background=True)
    await db.jjc_ranking_cache.create_index(
        "created_at", expireAfterSeconds=7200, background=True
    )

    # reminders
    await db.reminders.create_index("reminder_id", unique=True, background=True)
    await db.reminders.create_index(
        [("group_id", 1), ("status", 1)], background=True
    )
    await db.reminders.create_index(
        [("status", 1), ("remind_at", 1)], background=True
    )

    # wanbaolou_subscriptions
    await db.wanbaolou_subscriptions.create_index("user_id", background=True)
    await db.wanbaolou_subscriptions.create_index(
        [("user_id", 1), ("item_name", 1)], unique=True, background=True
    )

    # group_configs
    await db.group_configs.create_index("group_id", unique=True, background=True)

    # runtime_config (单文档，无需额外索引)
    logger.info("MongoDB 索引初始化完成 ({} 个集合)", 10)
