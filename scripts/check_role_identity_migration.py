"""
迁移后只读核验脚本：检查 role_identities 与 role_jjc_cache 的数据质量。

用法:
  python scripts/check_role_identity_migration.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


def get_mongo_uri() -> str:
    """读取 MONGO_URI：优先 runtime_config.json，再环境变量。"""
    _script_dir = Path(__file__).resolve().parent
    _runtime_cfg_path = _script_dir.parent / "runtime_config.json"
    if _runtime_cfg_path.is_file():
        try:
            with open(str(_runtime_cfg_path), "r", encoding="utf-8") as fh:
                runtime_cfg = json.load(fh)
            uri = runtime_cfg.get("MONGO_URI")
            if uri:
                return str(uri)
        except Exception:
            pass

    uri = os.getenv("MONGO_URI")
    if uri:
        return uri

    raise RuntimeError(
        "无法获取 MONGO_URI：runtime_config.json 或环境变量均未配置"
    )


async def _collect_keys(db: AsyncIOMotorDatabase, collection: str) -> Set[str]:
    """聚合收集指定集合中所有 identity_key。"""
    cursor = db[collection].aggregate([{"$group": {"_id": "$identity_key"}}])
    rows = await cursor.to_list(None)
    # 过滤可能的 null key
    return {row["_id"] for row in rows if row["_id"] is not None}


async def check(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """执行全部核验查询，返回结果字典。"""

    # ---- 1. 集合文档总数 ----
    identity_count = await db.role_identities.count_documents({})
    jjc_count = await db.role_jjc_cache.count_documents({})
    print("=" * 60)
    print("1. 集合文档总数")
    print("=" * 60)
    print("  role_identities:  {}".format(identity_count))
    print("  role_jjc_cache:   {}".format(jjc_count))
    print()

    # ---- 2. identity_level 分布 ----
    pipeline = [
        {"$group": {"_id": "$identity_level", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    level_rows = await db.role_identities.aggregate(pipeline).to_list(None)
    level_dist: Dict[str, int] = {}
    for row in level_rows:
        key = row["_id"] if row["_id"] is not None else "(缺失)"
        level_dist[key] = row["count"]
    print("=" * 60)
    print("2. role_identities identity_level 分布")
    print("=" * 60)
    for level in sorted(level_dist):
        print("  {}: {}".format(level, level_dist[level]))
    print()

    # ---- 3. identity_key 差集 ----
    identity_keys = await _collect_keys(db, "role_identities")
    jjc_keys = await _collect_keys(db, "role_jjc_cache")

    only_in_identity = identity_keys - jjc_keys
    only_in_jjc = jjc_keys - identity_keys
    common_keys = identity_keys & jjc_keys

    print("=" * 60)
    print("3. identity_key 差集")
    print("=" * 60)
    print("  role_identities 中 key 种类:  {}".format(len(identity_keys)))
    print("  role_jjc_cache 中 key 种类:   {}".format(len(jjc_keys)))
    print("  两边共有 key:                 {}".format(len(common_keys)))
    print("  仅在 role_identities 中:      {}".format(len(only_in_identity)))
    print("  仅在 role_jjc_cache 中:       {}".format(len(only_in_jjc)))
    if only_in_identity:
        print("  仅在 role_identities 的 key (前 10):")
        for k in sorted(only_in_identity)[:10]:
            print("    - {}".format(k))
    if only_in_jjc:
        print("  仅在 role_jjc_cache 的 key (前 10):")
        for k in sorted(only_in_jjc)[:10]:
            print("    - {}".format(k))
    print()

    # ---- 4. role_jjc_cache checked_at 缺失 ----
    missing_checked_at = await db.role_jjc_cache.count_documents(
        {"checked_at": {"$exists": False}}
    )
    null_checked_at = await db.role_jjc_cache.count_documents(
        {"checked_at": None}
    )
    print("=" * 60)
    print("4. role_jjc_cache checked_at 缺失")
    print("=" * 60)
    print("  缺少 checked_at 字段: {}".format(missing_checked_at))
    print("  checked_at 为 null:    {}".format(null_checked_at))
    print()

    # ---- 5. 潜在异常检查 ----

    # 5a. role_identities 同一 global_role_id 多记录
    dup_global = await db.role_identities.aggregate([
        {"$match": {"global_role_id": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$group": {
            "_id": "$global_role_id",
            "keys": {"$push": "$identity_key"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]).to_list(None)
    print("=" * 60)
    print("5a. role_identities 同一 global_role_id 多记录")
    print("=" * 60)
    print("  重复 global_role_id 组数: {}".format(len(dup_global)))
    for item in dup_global[:10]:
        print("    global_role_id={}  count={}  keys={}".format(
            item["_id"], item["count"], item["keys"][:5],
        ))
    print()

    # 5b. role_identities 同一 zone+game_role_id 多记录
    dup_zone_game = await db.role_identities.aggregate([
        {"$match": {
            "zone": {"$exists": True, "$ne": None, "$ne": ""},
            "game_role_id": {"$exists": True, "$ne": None, "$ne": ""},
        }},
        {"$group": {
            "_id": {"zone": "$zone", "game_role_id": "$game_role_id"},
            "keys": {"$push": "$identity_key"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]).to_list(None)
    print("=" * 60)
    print("5b. role_identities 同一 zone+game_role_id 多记录")
    print("=" * 60)
    print("  重复 (zone, game_role_id) 组数: {}".format(len(dup_zone_game)))
    for item in dup_zone_game[:10]:
        zid = item["_id"]
        print("    zone={}  game_role_id={}  count={}  keys={}".format(
            zid["zone"], zid["game_role_id"], item["count"], item["keys"][:5],
        ))
    print()

    # 5c. role_jjc_cache 同一 global_role_id 多记录
    dup_global_jjc = await db.role_jjc_cache.aggregate([
        {"$match": {"global_role_id": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$group": {
            "_id": "$global_role_id",
            "keys": {"$push": "$identity_key"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]).to_list(None)
    print("=" * 60)
    print("5c. role_jjc_cache 同一 global_role_id 多记录")
    print("=" * 60)
    print("  重复 global_role_id 组数: {}".format(len(dup_global_jjc)))
    for item in dup_global_jjc[:10]:
        print("    global_role_id={}  count={}  keys={}".format(
            item["_id"], item["count"], item["keys"][:5],
        ))
    print()

    # 5d. role_jjc_cache 同一 zone+game_role_id 多记录
    dup_zone_game_jjc = await db.role_jjc_cache.aggregate([
        {"$match": {
            "zone": {"$exists": True, "$ne": None, "$ne": ""},
            "game_role_id": {"$exists": True, "$ne": None, "$ne": ""},
        }},
        {"$group": {
            "_id": {"zone": "$zone", "game_role_id": "$game_role_id"},
            "keys": {"$push": "$identity_key"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]).to_list(None)
    print("=" * 60)
    print("5d. role_jjc_cache 同一 zone+game_role_id 多记录")
    print("=" * 60)
    print("  重复 (zone, game_role_id) 组数: {}".format(len(dup_zone_game_jjc)))
    for item in dup_zone_game_jjc[:10]:
        zid = item["_id"]
        print("    zone={}  game_role_id={}  count={}  keys={}".format(
            zid["zone"], zid["game_role_id"], item["count"], item["keys"][:5],
        ))
    print()

    # ---- 汇总 ----
    print("=" * 60)
    print("核验摘要")
    print("=" * 60)
    print("  role_identities 总数:              {}".format(identity_count))
    print("  role_jjc_cache 总数:               {}".format(jjc_count))
    print("  identity_level 分布:               {}".format(level_dist))
    print("  两边共有 identity_key:             {}".format(len(common_keys)))
    print("  仅 role_identities 的 key 数:      {}".format(len(only_in_identity)))
    print("  仅 role_jjc_cache 的 key 数:       {}".format(len(only_in_jjc)))
    print("  jjc_cache 缺 checked_at 字段:      {}".format(missing_checked_at))
    print("  jjc_cache checked_at 为 null:      {}".format(null_checked_at))
    print("  global_role_id 重复 (identity):    {} 组".format(len(dup_global)))
    print("  zone+game_role_id 重复 (identity): {} 组".format(len(dup_zone_game)))
    print("  global_role_id 重复 (jjc):         {} 组".format(len(dup_global_jjc)))
    print("  zone+game_role_id 重复 (jjc):      {} 组".format(len(dup_zone_game_jjc)))

    return {
        "role_identities_count": identity_count,
        "role_jjc_cache_count": jjc_count,
        "identity_level_distribution": level_dist,
        "identity_keys_only_in_role_identities": len(only_in_identity),
        "identity_keys_only_in_role_jjc_cache": len(only_in_jjc),
        "jjc_cache_missing_checked_at": missing_checked_at,
        "jjc_cache_null_checked_at": null_checked_at,
        "duplicate_global_role_id_count": len(dup_global),
        "duplicate_zone_game_role_id_count": len(dup_zone_game),
        "duplicate_global_role_id_jjc_count": len(dup_global_jjc),
        "duplicate_zone_game_role_id_jjc_count": len(dup_zone_game_jjc),
    }


async def main() -> None:
    try:
        uri = get_mongo_uri()
    except RuntimeError as exc:
        print("错误: {}".format(exc))
        sys.exit(1)

    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        uri, maxPoolSize=10, serverSelectionTimeoutMS=5000,
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:
        print("MongoDB 连接失败: {}".format(exc))
        sys.exit(1)

    db = client[db_name]
    print("MongoDB 连接成功: {}".format(db_name))
    print()

    await check(db)

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
