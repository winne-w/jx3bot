#!/usr/bin/env python3
"""Clear JJC role identity related Mongo collections after backup verification."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
)
ALLOWED_COLLECTIONS = {
    "role_identities",
    "jjc_sync_role_queue",
    "role_jjc_cache",
    "jjc_role_indicator",
    "jjc_match_detail",
}
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
        if not name:
            continue
        if name not in ALLOWED_COLLECTIONS:
            raise ValueError(
                "不允许清理集合: {}。允许集合: {}".format(
                    name,
                    ",".join(sorted(ALLOWED_COLLECTIONS)),
                )
            )
        result.append(name)
    if not result:
        raise ValueError("--collections 不能为空")
    return result


def backup_name(collection: str, tag: str) -> str:
    return "{}_backup_{}".format(collection, tag)


def verify_backup_exists(db: Any, collections: Iterable[str], backup_tag: str) -> None:
    existing = set(db.list_collection_names())
    missing = [
        backup_name(collection, backup_tag)
        for collection in collections
        if backup_name(collection, backup_tag) not in existing
    ]
    if missing:
        raise RuntimeError(
            "缺少备份集合，拒绝清理: {}。请先执行备份或使用 --no-backup-check".format(
                ",".join(missing)
            )
        )


def clear_collections(
    db: Any,
    *,
    collections: Iterable[str],
    apply: bool,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    existing = set(db.list_collection_names())
    for collection in collections:
        exists = collection in existing
        before_count = db[collection].count_documents({}) if exists else 0
        item = {
            "collection": collection,
            "exists": exists,
            "before_count": before_count,
            "deleted_count": 0,
            "status": "dry_run",
        }
        results.append(item)
        if not exists:
            item["status"] = "source_missing"
            _log("[SKIP] source_missing collection={}".format(collection))
            continue
        if not apply:
            _log("[DRY_RUN] collection={} count={}".format(collection, before_count))
            continue

        result = db[collection].delete_many({})
        item["deleted_count"] = int(result.deleted_count)
        item["status"] = "cleared"
        if item["deleted_count"] != before_count:
            item["status"] = "delete_count_mismatch"
            raise RuntimeError(
                "清理数量不一致: collection={} before_count={} deleted={}".format(
                    collection,
                    before_count,
                    item["deleted_count"],
                )
            )
        _log("[OK] collection={} deleted={}".format(collection, item["deleted_count"]))

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "collections": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="清空 JJC 身份治理相关 Mongo 集合")
    parser.add_argument(
        "--collections",
        default="default",
        help="逗号分隔集合名；默认只清 role_identities,jjc_sync_role_queue",
    )
    parser.add_argument("--backup-tag", default="", help="清理前必须存在的备份 tag")
    parser.add_argument("--no-backup-check", action="store_true", help="跳过备份集合存在性检查")
    parser.add_argument("--apply", action="store_true", help="真正清空集合")
    parser.add_argument("--yes", action="store_true", help="与 --apply 同时使用，确认执行")
    args = parser.parse_args()

    if args.apply and not args.yes:
        raise SystemExit("--apply 需要同时传 --yes")
    if args.apply and not args.no_backup_check and not args.backup_tag.strip():
        raise SystemExit("--apply 默认需要 --backup-tag；如确认无备份清理，传 --no-backup-check")

    collections = parse_collections(args.collections)
    uri = get_mongo_uri()
    db_name = get_db_name(uri)
    client = MongoClient(uri)
    db = client[db_name]
    try:
        if args.apply and not args.no_backup_check:
            verify_backup_exists(db, collections, args.backup_tag.strip())

        _log("[INFO] db={} apply={} collections={}".format(
            db_name,
            args.apply,
            ",".join(collections),
        ))
        result = clear_collections(db, collections=collections, apply=args.apply)
        if args.apply:
            db[METADATA_COLLECTION].insert_one({
                **result,
                "type": "jjc_role_identity_clear",
                "db": db_name,
                "backup_tag": args.backup_tag.strip() or None,
                "backup_check_skipped": bool(args.no_backup_check),
            })
            _log("[OK] metadata_collection={}".format(METADATA_COLLECTION))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
