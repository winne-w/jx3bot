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
    """幂等创建所有集合的索引。已存在的索引会被跳过，数据冲突仅警告不阻塞。"""
    from pymongo.errors import DuplicateKeyError, OperationFailure

    async def _safe_index(collection_name: str, keys, *, name: str, **kwargs):
        col = db[collection_name]
        try:
            await col.create_index(keys, name=name, **kwargs)
        except DuplicateKeyError:
            logger.warning(f"索引创建跳过(数据冲突): collection={collection_name} index={name}")
        except OperationFailure as exc:
            if "already exists" in str(exc).lower() or exc.code == 85:
                return  # 索引已存在，正常
            logger.warning(f"索引创建失败: collection={collection_name} index={name} error={exc}")

    # server_master_cache
    await _safe_index("server_master_cache", "key", name="idx_key", unique=True)
    await _safe_index("server_master_cache", "cached_at", name="idx_cached_at", expireAfterSeconds=604800)

    # status_cache
    await _safe_index("status_cache", "cache_name", name="idx_cache_name", unique=True)

    # jjc_role_recent
    await _safe_index(
        "jjc_role_recent", [("server", 1), ("name", 1)], name="idx_server_name", unique=True
    )
    await _safe_index("jjc_role_recent", "cached_at", name="idx_cached_at", expireAfterSeconds=600)

    # jjc_match_detail
    await _safe_index("jjc_match_detail", "match_id", name="idx_match_id", unique=True)

    # jjc_ranking_cache
    await _safe_index("jjc_ranking_cache", "cache_key", name="idx_cache_key", unique=True)
    await _safe_index("jjc_ranking_cache", "created_at", name="idx_created_at", expireAfterSeconds=7200)

    # reminders
    await _safe_index("reminders", "reminder_id", name="idx_reminder_id", unique=True)
    await _safe_index(
        "reminders", [("group_id", 1), ("status", 1)], name="idx_group_status"
    )
    await _safe_index(
        "reminders", [("status", 1), ("remind_at", 1)], name="idx_status_remind_at"
    )

    # wanbaolou_subscriptions
    await _safe_index("wanbaolou_subscriptions", "user_id", name="idx_user_id")
    await _safe_index(
        "wanbaolou_subscriptions",
        [("user_id", 1), ("item_name", 1)],
        name="idx_user_item",
        unique=True,
    )

    # group_configs
    await _safe_index("group_configs", "group_id", name="idx_group_id", unique=True)

    # role_identities
    await _safe_index("role_identities", "identity_key", name="idx_identity_key", unique=True)
    await _safe_index(
        "role_identities", "global_role_id", name="idx_global_role_id", unique=True,
        partialFilterExpression={"global_role_id": {"$type": "string"}},
    )
    await _safe_index(
        "role_identities", [("zone", 1), ("game_role_id", 1)],
        name="idx_zone_game_role_id", unique=True,
        partialFilterExpression={"zone": {"$type": "string"}, "game_role_id": {"$type": "string"}},
    )
    await _safe_index(
        "role_identities", [("normalized_server", 1), ("normalized_name", 1)],
        name="idx_normalized_server_name",
    )
    await _safe_index("role_identities", "last_seen_at", name="idx_last_seen_at")

    # jjc_equipment_snapshot
    await _safe_index("jjc_equipment_snapshot", "snapshot_hash", name="idx_snapshot_hash", unique=True)
    await _safe_index("jjc_equipment_snapshot", "last_seen_at", name="idx_last_seen_at")

    # jjc_talent_snapshot
    await _safe_index("jjc_talent_snapshot", "snapshot_hash", name="idx_snapshot_hash", unique=True)
    await _safe_index("jjc_talent_snapshot", "last_seen_at", name="idx_last_seen_at")

    # role_jjc_cache
    await _safe_index("role_jjc_cache", "identity_key", name="idx_identity_key", unique=True)
    await _safe_index("role_jjc_cache", "global_role_id", name="idx_global_role_id")
    await _safe_index(
        "role_jjc_cache", [("zone", 1), ("game_role_id", 1)],
        name="idx_zone_game_role_id",
    )
    await _safe_index(
        "role_jjc_cache", [("normalized_server", 1), ("normalized_name", 1)],
        name="idx_normalized_server_name",
    )
    await _safe_index("role_jjc_cache", "checked_at", name="idx_checked_at", expireAfterSeconds=604800)

    logger.info("MongoDB 索引初始化完成")
