#!/usr/bin/env python3
"""Limit existing JJC sync queue tasks to a recent time window.

Default mode is dry-run. Use --apply to update MongoDB.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TARGET_STATUSES = ("pending", "cooldown", "exhausted", "failed", "queued")
MIGRATION_BY = "script:limit_existing_jjc_queue_to_7d"


def _log(message: str) -> None:
    print(message, flush=True)


def get_mongo_uri() -> str:
    runtime_cfg_path = ROOT / "runtime_config.json"
    if runtime_cfg_path.is_file():
        try:
            with open(str(runtime_cfg_path), "r", encoding="utf-8") as fh:
                uri = json.load(fh).get("MONGO_URI")
            if uri:
                return str(uri)
        except Exception:
            pass

    try:
        from config import MONGO_URI  # type: ignore

        if MONGO_URI:
            return str(MONGO_URI)
    except Exception:
        pass

    uri = os.getenv("MONGO_URI")
    if uri:
        return uri
    raise RuntimeError("无法获取 MONGO_URI：runtime_config.json、config.MONGO_URI、环境变量均未配置")


def get_db(client: MongoClient, db_name: Optional[str]) -> Any:
    if db_name:
        return client[db_name]
    default_db = client.get_default_database(default=None)
    if default_db is not None:
        return default_db
    return client["jx3bot"]


def parse_statuses(raw: str) -> List[str]:
    statuses = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if not statuses:
        raise ValueError("statuses 不能为空")
    if "syncing" in statuses:
        raise ValueError("不允许修改 syncing 状态的队列记录")
    if "disabled" in statuses:
        raise ValueError("不允许修改 disabled 状态的队列记录")
    return statuses


def build_query(statuses: List[str]) -> Dict[str, Any]:
    return {"status": {"$in": statuses}}


def build_update(cutoff: int, now: float) -> Dict[str, Any]:
    return {
        "$set": {
            "queue_mode": "full",
            "queue_sync_until_time": cutoff,
            "updated_at": now,
            "queue_window_migrated_at": now,
            "queue_window_migrated_by": MIGRATION_BY,
        }
    }


def collection_name(db: Any) -> str:
    names = set(db.list_collection_names())
    if "jjc_sync_identity_queue" in names:
        return "jjc_sync_identity_queue"
    return "jjc_sync_role_queue"


def count_by_status(collection: Any, statuses: List[str]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for status in statuses:
        result[status] = int(collection.count_documents({"status": status}))
    return result


def load_samples(collection: Any, query: Dict[str, Any], sample_size: int) -> List[Dict[str, Any]]:
    projection = {
        "_id": 1,
        "server": 1,
        "name": 1,
        "status": 1,
        "priority": 1,
        "queue_mode": 1,
        "queue_source": 1,
        "queue_sync_until_time": 1,
        "queued_at": 1,
        "updated_at": 1,
    }
    cursor = collection.find(query, projection).sort([("status", 1), ("priority", -1), ("updated_at", 1)]).limit(sample_size)
    samples: List[Dict[str, Any]] = []
    for doc in cursor:
        samples.append({
            "_id": str(doc.get("_id")),
            "server": doc.get("server"),
            "name": doc.get("name"),
            "status": doc.get("status"),
            "priority": doc.get("priority"),
            "queue_mode": doc.get("queue_mode"),
            "queue_source": doc.get("queue_source"),
            "queue_sync_until_time": doc.get("queue_sync_until_time"),
            "queued_at": doc.get("queued_at"),
            "updated_at": doc.get("updated_at"),
        })
    return samples


def run(args: argparse.Namespace) -> int:
    statuses = parse_statuses(args.statuses)
    now = time.time()
    cutoff = int(now - args.days * 86400)
    query = build_query(statuses)
    update = build_update(cutoff, now)

    mongo_uri = args.mongo_uri or get_mongo_uri()
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=8000)
    try:
        client.admin.command("ping")
        db = get_db(client, args.db_name)
        col_name = args.collection or collection_name(db)
        collection = db[col_name]

        total = int(collection.count_documents(query))
        counts = count_by_status(collection, statuses)
        samples = load_samples(collection, query, args.sample_size)

        _log("集合: {}".format(col_name))
        _log("模式: {}".format("apply" if args.apply else "dry-run"))
        _log("目标状态: {}".format(",".join(statuses)))
        _log("days: {}  cutoff: {}".format(args.days, cutoff))
        _log("匹配总数: {}".format(total))
        _log("按状态统计: {}".format(json.dumps(counts, ensure_ascii=False, sort_keys=True)))
        if samples:
            _log("样例:")
            for item in samples:
                _log("  {}".format(json.dumps(item, ensure_ascii=False, sort_keys=True)))

        if not args.apply:
            _log("dry-run 完成，未写入。确认无误后加 --apply 执行。")
            return 0

        result = collection.update_many(query, update)
        _log("写入完成: matched={} modified={}".format(result.matched_count, result.modified_count))
        return 0
    finally:
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将历史 JJC 同步队列中未执行/排队任务限制为最近 N 天窗口，默认 dry-run。",
    )
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只预览")
    parser.add_argument("--days", type=int, default=14, help="同步最近多少天，默认 14")
    parser.add_argument(
        "--statuses",
        default="pending,cooldown,exhausted,failed,queued",
        help="要处理的状态，逗号分隔；不允许 syncing/disabled",
    )
    parser.add_argument("--sample-size", type=int, default=10, help="dry-run 样例数量")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI；默认读取 runtime_config/config/env")
    parser.add_argument("--db-name", default=None, help="数据库名；默认取 URI database 或 jx3bot")
    parser.add_argument("--collection", default=None, help="队列集合名；默认优先 jjc_sync_identity_queue")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days 必须是正整数")
    if args.sample_size < 0:
        parser.error("--sample-size 不能小于 0")
    try:
        return run(args)
    except Exception as exc:
        _log("执行失败: {}".format(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
