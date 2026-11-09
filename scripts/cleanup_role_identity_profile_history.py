#!/usr/bin/env python3
"""Remove deprecated profile_history arrays from role_identities."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from bson import BSON
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage.mongo_repos.role_identity_repo import MATCH_DETAIL_IDENTITY_PROJECTION  # noqa: E402


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


def _get_db(client: MongoClient, db_name: Optional[str]) -> Any:
    if db_name:
        return client[db_name]
    default_db = client.get_default_database(default=None)
    if default_db is not None:
        return default_db
    return client["jx3bot"]


def _bson_size(doc: Dict[str, Any]) -> int:
    return len(BSON.encode(doc))


def _timed_find_one(collection: Any, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None) -> float:
    started_at = time.perf_counter()
    if projection is None:
        collection.find_one(query)
    else:
        collection.find_one(query, projection)
    return (time.perf_counter() - started_at) * 1000


def collect_sample_stats(collection: Any, sample_size: int) -> Dict[str, Any]:
    projection = {
        "_id": 1,
        "identity_key": 1,
        "server": 1,
        "name": 1,
        "profile_history": 1,
    }
    cursor = collection.find(
        {"profile_history": {"$exists": True}},
        projection,
    ).sort([("_id", 1)]).limit(sample_size)
    samples: List[Dict[str, Any]] = list(cursor)

    max_history_len = 0
    max_bson_size = 0
    full_read_ms: List[float] = []
    slim_read_ms: List[float] = []
    sample_rows: List[Dict[str, Any]] = []

    for doc in samples:
        history = doc.get("profile_history")
        history_len = len(history) if isinstance(history, list) else 0
        max_history_len = max(max_history_len, history_len)

        identity_key = doc.get("identity_key")
        query = {"_id": doc["_id"]}
        full_doc = collection.find_one(query)
        if isinstance(full_doc, dict):
            max_bson_size = max(max_bson_size, _bson_size(full_doc))

        full_read_ms.append(_timed_find_one(collection, query))
        slim_read_ms.append(_timed_find_one(collection, query, MATCH_DETAIL_IDENTITY_PROJECTION))
        sample_rows.append({
            "identity_key": identity_key,
            "server": doc.get("server"),
            "name": doc.get("name"),
            "profile_history_len": history_len,
        })

    def median(values: List[float]) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[len(ordered) // 2]

    return {
        "sample_count": len(samples),
        "max_profile_history_len": max_history_len,
        "max_bson_size": max_bson_size,
        "full_read_ms_median": median(full_read_ms),
        "slim_read_ms_median": median(slim_read_ms),
        "samples": sample_rows,
    }


def run(args: argparse.Namespace) -> int:
    mongo_uri = args.mongo_uri or get_mongo_uri()
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=8000)
    try:
        client.admin.command("ping")
        db = _get_db(client, args.db_name)
        collection = db.role_identities

        query = {"profile_history": {"$exists": True}}
        before_count = collection.count_documents(query)
        _log("role_identities profile_history 待清理文档数: {}".format(before_count))

        stats = collect_sample_stats(collection, args.sample_size)
        _log("抽样文档数: {}".format(stats["sample_count"]))
        _log("抽样最大 profile_history 长度: {}".format(stats["max_profile_history_len"]))
        _log("抽样最大 BSON 大小: {} bytes".format(stats["max_bson_size"]))
        _log("抽样完整读取中位耗时: {} ms".format(stats["full_read_ms_median"]))
        _log("抽样瘦投影读取中位耗时: {} ms".format(stats["slim_read_ms_median"]))
        if stats["samples"]:
            _log("抽样样本:")
            for row in stats["samples"]:
                _log("  - identity_key={identity_key} server={server} name={name} profile_history_len={profile_history_len}".format(**row))

        if not args.execute:
            _log("dry-run 完成；如需写库，请追加 --execute。")
            return 0

        result = collection.update_many(query, {"$unset": {"profile_history": ""}})
        after_count = collection.count_documents(query)
        _log("清理完成: matched={} modified={} remaining={}".format(
            result.matched_count,
            result.modified_count,
            after_count,
        ))
        return 0 if after_count == 0 else 2
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 role_identities.profile_history 废弃字段")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI；默认读取 runtime_config/config/env")
    parser.add_argument("--db-name", default=None, help="数据库名；默认使用 URI 默认库或 jx3bot")
    parser.add_argument("--sample-size", type=int, default=5, help="抽样文档数")
    parser.add_argument("--dry-run", action="store_true", help="只读预览；默认行为，保留该参数用于显式调用")
    parser.add_argument("--execute", action="store_true", help="实际执行 $unset；默认只 dry-run")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
