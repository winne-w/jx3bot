"""
迁移 data/cache/kungfu/*.json 心法缓存到 MongoDB kungfu_cache 集合。

用法: python scripts/migrate_kungfu_cache.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from motor.motor_asyncio import AsyncIOMotorDatabase


async def migrate_kungfu_cache(db: AsyncIOMotorDatabase) -> None:
    cache_dir = "data/cache/kungfu"
    if not os.path.isdir(cache_dir):
        print(f"目录不存在: {cache_dir}")
        return

    files = sorted(f for f in os.listdir(cache_dir) if f.endswith(".json"))
    total = len(files)
    if total == 0:
        print("没有需要迁移的文件")
        return

    success = 0
    skipped = 0
    failed = 0
    start_time = time.time()

    for i, filename in enumerate(files):
        filepath = os.path.join(cache_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            failed += 1
            print(f"[{i+1}/{total}] 读取失败: {filename} error={exc}")
            continue

        server = data.get("server")
        name = data.get("name")
        if not server or not name:
            skipped += 1
            print(f"[{i+1}/{total}] 跳过(缺少 server/name): {filename}")
            continue

        try:
            await db.kungfu_cache.update_one(
                {"server": server, "name": name},
                {"$set": data},
                upsert=True,
            )
            success += 1
        except Exception as exc:
            failed += 1
            print(f"[{i+1}/{total}] 写入失败: {filename} error={exc}")
            continue

        if (i + 1) % 500 == 0:
            elapsed = time.time() - start_time
            print(f"进度: {i+1}/{total} 成功={success} 跳过={skipped} 失败={failed} 耗时={elapsed:.1f}s")

    elapsed = time.time() - start_time
    print(f"迁移完成: 总数={total} 成功={success} 跳过={skipped} 失败={failed} 耗时={elapsed:.1f}s")


async def main():
    # 读取运行时配置获取 MONGO_URI
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

    existing = await db.kungfu_cache.estimated_document_count()
    print(f"目标集合现有文档数: {existing}")

    await migrate_kungfu_cache(db)

    final = await db.kungfu_cache.estimated_document_count()
    print(f"迁移后集合文档数: {final}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
