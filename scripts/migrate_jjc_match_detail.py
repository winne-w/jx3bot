"""
迁移 data/cache/jjc_ranking_inspect/match_detail/*.json 到 MongoDB jjc_match_detail 集合。

用法: python scripts/migrate_jjc_match_detail.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time


async def migrate_match_detail(db) -> None:
    base_dir = "data/cache/jjc_ranking_inspect/match_detail"
    if not os.path.isdir(base_dir):
        print(f"目录不存在: {base_dir}")
        return

    files = sorted(
        f for f in os.listdir(base_dir) if f.endswith(".json") and f[:-5].isdigit()
    )
    total = len(files)
    if total == 0:
        print("没有需要迁移的文件")
        return

    success = 0
    failed = 0
    start_time = time.time()

    for i, filename in enumerate(files):
        filepath = os.path.join(base_dir, filename)
        match_id = int(filename[:-5])  # 去掉 .json

        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            failed += 1
            print(f"[{i+1}/{total}] 读取失败: match_id={match_id} error={exc}")
            continue

        cached_at = data.get("cached_at", time.time())
        payload_data = data.get("data", data)

        try:
            await db.jjc_match_detail.update_one(
                {"match_id": match_id},
                {"$set": {
                    "cached_at": cached_at,
                    "data": payload_data,
                }},
                upsert=True,
            )
            success += 1
        except Exception as exc:
            failed += 1
            print(f"[{i+1}/{total}] 写入失败: match_id={match_id} error={exc}")
            continue

        if (i + 1) % 200 == 0:
            elapsed = time.time() - start_time
            print(f"进度: {i+1}/{total} 成功={success} 失败={failed} 耗时={elapsed:.1f}s")

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

    existing = await db.jjc_match_detail.estimated_document_count()
    print(f"目标集合现有文档数: {existing}")

    await migrate_match_detail(db)

    final = await db.jjc_match_detail.estimated_document_count()
    print(f"迁移后集合文档数: {final}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
