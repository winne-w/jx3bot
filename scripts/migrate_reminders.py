"""
迁移 data/group_reminders.json 到 MongoDB reminders 集合。

原有格式: {group_id: [{id, group_id, creator_user_id, ...}, ...]}
新格式:    每提醒一条文档，id → reminder_id

用法: python scripts/migrate_reminders.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time


async def migrate_reminders(db) -> None:
    file_path = "data/group_reminders.json"
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}（空库正常状态）")
        return

    with open(file_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict) or not data:
        print("提醒文件为空")
        return

    total = sum(len(reminders) for reminders in data.values())
    success = 0
    failed = 0
    start_time = time.time()

    for group_id, reminders in data.items():
        for reminder in reminders:
            # 重命名 id → reminder_id
            if "id" in reminder and "reminder_id" not in reminder:
                reminder["reminder_id"] = reminder.pop("id")
            if "reminder_id" not in reminder:
                continue
            try:
                await db.reminders.update_one(
                    {"reminder_id": reminder["reminder_id"]},
                    {"$set": reminder},
                    upsert=True,
                )
                success += 1
            except Exception as exc:
                failed += 1
                print(f"写入失败: reminder_id={reminder.get('reminder_id')} error={exc}")

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

    existing = await db.reminders.estimated_document_count()
    print(f"目标集合现有文档数: {existing}")

    await migrate_reminders(db)

    final = await db.reminders.estimated_document_count()
    print(f"迁移后集合文档数: {final}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
