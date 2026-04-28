"""
迁移 data/cache/jjc_ranking_inspect/role_recent/*.json 到 MongoDB jjc_role_recent 集合。

目录结构: role_recent/{server_enc}/{name_enc}.json （URL 编码）
用法: python scripts/migrate_jjc_role_recent.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from urllib.parse import unquote

from motor.motor_asyncio import AsyncIOMotorDatabase


async def migrate_role_recent(db: AsyncIOMotorDatabase) -> None:
    base_dir = "data/cache/jjc_ranking_inspect/role_recent"
    if not os.path.isdir(base_dir):
        print(f"目录不存在: {base_dir}")
        return

    # 收集所有 JSON 文件
    files: list[tuple[str, str, str]] = []  # (filepath, server, name)
    for dirname in os.listdir(base_dir):
        dirpath = os.path.join(base_dir, dirname)
        if not os.path.isdir(dirpath):
            continue
        server = unquote(dirname)
        for filename in os.listdir(dirpath):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(dirpath, filename)
            name = unquote(filename[:-5])  # 去掉 .json
            files.append((filepath, server, name))

    total = len(files)
    if total == 0:
        print("没有需要迁移的文件")
        return

    success = 0
    failed = 0
    start_time = time.time()

    for i, (filepath, server, name) in enumerate(files):
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            failed += 1
            print(f"[{i+1}/{total}] 读取失败: {filepath} error={exc}")
            continue

        cached_at = data.get("cached_at", time.time())
        payload_data = data.get("data", data)

        try:
            await db.jjc_role_recent.update_one(
                {"server": server, "name": name},
                {"$set": {
                    "cached_at": cached_at,
                    "data": payload_data,
                }},
                upsert=True,
            )
            success += 1
        except Exception as exc:
            failed += 1
            print(f"[{i+1}/{total}] 写入失败: server={server} name={name} error={exc}")
            continue

        if (i + 1) % 100 == 0:
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

    existing = await db.jjc_role_recent.estimated_document_count()
    print(f"目标集合现有文档数: {existing}")

    await migrate_role_recent(db)

    final = await db.jjc_role_recent.estimated_document_count()
    print(f"迁移后集合文档数: {final}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
