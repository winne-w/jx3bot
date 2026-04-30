"""
清空 JJC 对局详情快照相关集合。

默认 dry-run 模式，只统计不删除。

用法:
  python scripts/clear_jjc_match_detail_snapshot_cache.py
  python scripts/clear_jjc_match_detail_snapshot_cache.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

TARGET_COLLECTIONS = [
    "jjc_match_detail",
    "jjc_equipment_snapshot",
    "jjc_talent_snapshot",
]


def _get_mongo_uri() -> str:
    """读取 MONGO_URI：优先环境变量，其次 runtime_config.json。"""
    uri = os.getenv("MONGO_URI")
    if uri:
        return uri

    script_dir = Path(__file__).resolve().parent
    runtime_cfg_path = script_dir.parent / "runtime_config.json"
    if runtime_cfg_path.is_file():
        try:
            with open(str(runtime_cfg_path), "r", encoding="utf-8") as fh:
                runtime_cfg = json.load(fh)
            uri = runtime_cfg.get("MONGO_URI")
            if uri:
                return str(uri)
        except Exception:
            pass

    raise RuntimeError(
        "无法获取 MONGO_URI：环境变量 MONGO_URI 和 runtime_config.json 均未配置"
    )


async def _get_counts(db: AsyncIOMotorDatabase, collections: List[str]) -> Dict[str, int]:
    """获取各集合的文档计数。"""
    counts: Dict[str, int] = {}
    for col_name in collections:
        try:
            counts[col_name] = await db[col_name].estimated_document_count()
        except Exception:
            counts[col_name] = -1
    return counts


def _print_counts(counts: Dict[str, int], label: str) -> None:
    """格式化输出集合计数。"""
    print()
    print("=" * 50)
    print("  {} 集合文档数".format(label))
    print("=" * 50)
    total = 0
    for col_name in TARGET_COLLECTIONS:
        cnt = counts.get(col_name, -1)
        marker = " (跳过)" if cnt == -1 else ""
        print("  {}: {}{}".format(col_name, cnt, marker))
        if cnt > 0:
            total += cnt
    print("  ---")
    print("  合计: {}".format(total))
    sys.stdout.flush()


async def run_clear(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """执行清空操作，返回各集合删除的文档数。"""
    stats: Dict[str, Any] = {}
    collections_to_clear = list(TARGET_COLLECTIONS)

    for col_name in collections_to_clear:
        try:
            result = await db[col_name].delete_many({})
            stats[col_name] = result.deleted_count
            print("  已清空 {}: {} 条文档".format(col_name, result.deleted_count))
        except Exception as exc:
            print("  清空 {} 失败: {}".format(col_name, exc))
            stats[col_name] = -1
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="清空 JJC 对局详情快照相关集合"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="实际执行清空。未指定时为 dry-run 模式，只统计不删除。",
    )
    args = parser.parse_args()

    try:
        uri = _get_mongo_uri()
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

    # 操作前计数
    before_counts = await _get_counts(db, TARGET_COLLECTIONS)
    _print_counts(before_counts, "清空前")

    if args.apply:
        print()
        print(">>> --apply 已指定，将实际执行清空 <<<")
        stats = await run_clear(db)

        # 操作后计数
        after_counts = await _get_counts(db, TARGET_COLLECTIONS)
        _print_counts(after_counts, "清空后")

        print()
        print("清空完成:")
        for col_name, deleted in stats.items():
            status = "失败" if deleted == -1 else "{} 条".format(deleted)
            print("  {}: {}".format(col_name, status))
    else:
        print()
        print(">>> DRY-RUN 模式，未实际清空。使用 --apply 参数执行实际清空 <<<")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
