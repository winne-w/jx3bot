"""
迁移 data/wanbaolou_subscriptions.json 到 MongoDB wanbaolou_subscriptions 集合。

用法: python scripts/migrate_wanbaolou_subs.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time


async def migrate_wanbaolou_subs(db) -> None:
    file_path = "data/wanbaolou_subscriptions.json"
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict) or not data:
        print("订阅文件为空或格式不正确")
        return

    total = sum(len(subs) for subs in data.values())
    success = 0
    failed = 0
    start_time = time.time()

    for user_id, subs in data.items():
        for sub in subs:
            item_name = sub.get("item_name", "")
            if not item_name:
                continue
            try:
                await db.wanbaolou_subscriptions.update_one(
                    {"user_id": user_id, "item_name": item_name},
                    {"$set": {
                        "user_id": user_id,
                        "item_name": item_name,
                        "price_threshold": sub.get("price_threshold", 0),
                        "group_id": str(sub["group_id"]) if sub.get("group_id") else None,
                        "created_at": sub.get("created_at", time.time()),
                        "active": True,
                    }},
                    upsert=True,
                )
                success += 1
            except Exception as exc:
                failed += 1
                print(f"写入失败: user_id={user_id} item_name={item_name} error={exc}")

    elapsed = time.time() - start_time
    print(f"迁移完成: 总数={total} 成功={success} 失败={failed} 耗时={elapsed:.1f}s")


async def main():
    with open("runtime_config.json", "r", encoding="utf-8") as fh:
        runtime_cfg = json.load(fh)
    uri = runtime_cfg.get("MONGO_URI")
    if not uri:
        print("runtime_config.json 中未配置 MONGO_URI")
        return

    from motor.motor_asyncio import AsyncIOMotorClient

    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    client = AsyncIOMotorClient(uri, maxPoolSize=10, serverSelectionTimeoutMS=5000)
    await client.admin.command("ping")
    db = client[db_name]
    print(f"MongoDB 连接成功: {db_name}")

    existing = await db.wanbaolou_subscriptions.estimated_document_count()
    print(f"目标集合现有文档数: {existing}")

    await migrate_wanbaolou_subs(db)

    final = await db.wanbaolou_subscriptions.estimated_document_count()
    print(f"迁移后集合文档数: {final}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
