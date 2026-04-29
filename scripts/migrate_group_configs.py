"""
迁移 groups.json 到 MongoDB group_configs 集合。

原有格式: {group_id: {servers, 开服推送, ...}, ...}
新格式:    每群一条文档，group_id 作为唯一键

用法: python scripts/migrate_group_configs.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time


async def migrate_group_configs(db) -> None:
    file_path = "groups.json"
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}（空库正常状态）")
        return

    with open(file_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict) or not data:
        print("群配置文件为空")
        return

    total = len(data)
    success = 0
    failed = 0
    start_time = time.time()

    for group_id, config in data.items():
        if not isinstance(config, dict):
            print(f"跳过非 dict 记录: group_id={group_id}")
            continue
        doc = {"group_id": str(group_id), **config}
        try:
            await db.group_configs.update_one(
                {"group_id": str(group_id)},
                {"$set": doc},
                upsert=True,
            )
            success += 1
            print(f"  写入: group_id={group_id} server={config.get('servers', '?')}")
        except Exception as exc:
            failed += 1
            print(f"写入失败: group_id={group_id} error={exc}")

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

    existing = await db.group_configs.estimated_document_count()
    print(f"目标集合现有文档数: {existing}")

    await migrate_group_configs(db)

    final = await db.group_configs.estimated_document_count()
    print(f"迁移后集合文档数: {final}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
