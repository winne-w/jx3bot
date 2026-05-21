#!/usr/bin/env python3
"""Backup JJC role identity related Mongo collections before online migration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_COLLECTIONS = (
    "role_identities",
    "jjc_sync_role_queue",
    "role_jjc_cache",
    "jjc_role_indicator",
    "jjc_match_detail",
)
METADATA_COLLECTION = "jjc_backup_metadata"


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


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


def get_db_name(uri: str) -> str:
    name = uri.rsplit("/", 1)[-1].split("?", 1)[0]
    if not name:
        raise RuntimeError("无法从 MONGO_URI 解析数据库名")
    return name


def parse_collections(value: str) -> List[str]:
    if not value or value == "default":
        return list(DEFAULT_COLLECTIONS)
    result: List[str] = []
    for item in value.split(","):
        name = item.strip()
        if name:
            result.append(name)
    if not result:
        raise ValueError("--collections 不能为空")
    return result


def build_backup_name(collection: str, tag: str) -> str:
    return "{}_backup_{}".format(collection, tag)


def copy_collection(
    db: Any,
    *,
    source_name: str,
    backup_name: str,
    batch_size: int,
) -> int:
    source = db[source_name]
    target = db[backup_name]
    copied = 0
    batch: List[Dict[str, Any]] = []
    cursor = source.find({}, no_cursor_timeout=True).batch_size(batch_size)
    try:
        for doc in cursor:
            batch.append(doc)
            if len(batch) >= batch_size:
                target.insert_many(batch, ordered=True)
                copied += len(batch)
                batch = []
        if batch:
            target.insert_many(batch, ordered=True)
            copied += len(batch)
    finally:
        cursor.close()
    return copied


def backup_collections(
    db: Any,
    *,
    collections: Iterable[str],
    tag: str,
    apply: bool,
    overwrite: bool,
    batch_size: int,
) -> Dict[str, Any]:
    existing_collections = set(db.list_collection_names())
    results: List[Dict[str, Any]] = []

    for source_name in collections:
        backup_name = build_backup_name(source_name, tag)
        source_exists = source_name in existing_collections
        source_count = db[source_name].count_documents({}) if source_exists else 0
        target_exists = backup_name in existing_collections

        item = {
            "source": source_name,
            "backup": backup_name,
            "source_exists": source_exists,
            "source_count": source_count,
            "target_exists": target_exists,
            "copied_count": 0,
            "status": "dry_run",
        }
        results.append(item)

        if not source_exists:
            item["status"] = "source_missing"
            _log("[SKIP] source_missing source={} backup={}".format(source_name, backup_name))
            continue

        if not apply:
            _log("[DRY_RUN] source={} count={} backup={}".format(source_name, source_count, backup_name))
            continue

        if target_exists:
            if not overwrite:
                raise RuntimeError(
                    "备份集合已存在: {}。如确认覆盖，请加 --overwrite".format(backup_name)
                )
            db[backup_name].drop()
            _log("[DROP] existing_backup={}".format(backup_name))

        copied = copy_collection(
            db,
            source_name=source_name,
            backup_name=backup_name,
            batch_size=batch_size,
        )
        item["copied_count"] = copied
        item["status"] = "copied"
        if copied != source_count:
            item["status"] = "count_mismatch"
            raise RuntimeError(
                "备份数量不一致: source={} source_count={} copied={}".format(
                    source_name,
                    source_count,
                    copied,
                )
            )
        _log("[OK] source={} count={} backup={}".format(source_name, copied, backup_name))

    return {
        "tag": tag,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "collections": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="备份 JJC 身份治理相关 Mongo 集合")
    parser.add_argument("--collections", default="default", help="逗号分隔集合名；默认备份 JJC 身份相关集合")
    parser.add_argument("--tag", default="", help="备份标签；默认使用当前时间戳")
    parser.add_argument("--batch-size", type=int, default=1000, help="批量复制大小，默认 1000")
    parser.add_argument("--apply", action="store_true", help="真正写入备份集合")
    parser.add_argument("--yes", action="store_true", help="与 --apply 同时使用，确认执行")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖同名备份集合")
    args = parser.parse_args()

    if args.apply and not args.yes:
        raise SystemExit("--apply 需要同时传 --yes")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size 必须大于 0")

    uri = get_mongo_uri()
    db_name = get_db_name(uri)
    collections = parse_collections(args.collections)
    tag = args.tag.strip() or time.strftime("%Y%m%d_%H%M%S")

    client = MongoClient(uri)
    db = client[db_name]
    try:
        _log("[INFO] db={} tag={} apply={} collections={}".format(
            db_name,
            tag,
            args.apply,
            ",".join(collections),
        ))
        result = backup_collections(
            db,
            collections=collections,
            tag=tag,
            apply=args.apply,
            overwrite=args.overwrite,
            batch_size=args.batch_size,
        )
        if args.apply:
            db[METADATA_COLLECTION].insert_one({
                **result,
                "type": "jjc_role_identity_backup",
                "db": db_name,
            })
            _log("[OK] metadata_collection={} tag={}".format(METADATA_COLLECTION, tag))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
