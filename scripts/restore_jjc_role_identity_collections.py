#!/usr/bin/env python3
"""Restore JJC role identity related Mongo collections from backup collections."""

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


def backup_name(collection: str, tag: str) -> str:
    return "{}_backup_{}".format(collection, tag)


def pre_restore_backup_name(collection: str, tag: str) -> str:
    return "{}_pre_restore_backup_{}".format(collection, tag)


def copy_collection(
    db: Any,
    *,
    source_name: str,
    target_name: str,
    batch_size: int,
) -> int:
    source = db[source_name]
    target = db[target_name]
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


def restore_collections(
    db: Any,
    *,
    collections: Iterable[str],
    backup_tag: str,
    pre_restore_tag: str,
    apply: bool,
    batch_size: int,
) -> Dict[str, Any]:
    existing_collections = set(db.list_collection_names())
    results: List[Dict[str, Any]] = []

    for target_name in collections:
        source_name = backup_name(target_name, backup_tag)
        pre_backup_name = pre_restore_backup_name(target_name, pre_restore_tag)
        source_exists = source_name in existing_collections
        target_exists = target_name in existing_collections
        source_count = db[source_name].count_documents({}) if source_exists else 0
        target_count = db[target_name].count_documents({}) if target_exists else 0

        item = {
            "target": target_name,
            "backup": source_name,
            "pre_restore_backup": pre_backup_name,
            "backup_exists": source_exists,
            "target_exists": target_exists,
            "backup_count": source_count,
            "target_before_count": target_count,
            "restored_count": 0,
            "pre_restore_copied_count": 0,
            "status": "dry_run",
        }
        results.append(item)

        if not source_exists:
            item["status"] = "backup_missing"
            _log("[SKIP] backup_missing backup={} target={}".format(source_name, target_name))
            continue

        if not apply:
            _log("[DRY_RUN] backup={} count={} target={} current_count={} pre_restore_backup={}".format(
                source_name,
                source_count,
                target_name,
                target_count,
                pre_backup_name,
            ))
            continue

        if pre_backup_name in existing_collections:
            raise RuntimeError(
                "恢复前备份集合已存在: {}。请换 --pre-restore-tag".format(pre_backup_name)
            )

        if target_exists:
            copied_current = copy_collection(
                db,
                source_name=target_name,
                target_name=pre_backup_name,
                batch_size=batch_size,
            )
            item["pre_restore_copied_count"] = copied_current
            if copied_current != target_count:
                item["status"] = "pre_restore_count_mismatch"
                raise RuntimeError(
                    "恢复前备份数量不一致: target={} target_count={} copied={}".format(
                        target_name,
                        target_count,
                        copied_current,
                    )
                )
            db[target_name].drop()
            _log("[BACKUP_CURRENT] target={} count={} backup={}".format(
                target_name,
                copied_current,
                pre_backup_name,
            ))

        restored = copy_collection(
            db,
            source_name=source_name,
            target_name=target_name,
            batch_size=batch_size,
        )
        item["restored_count"] = restored
        item["status"] = "restored"
        if restored != source_count:
            item["status"] = "restore_count_mismatch"
            raise RuntimeError(
                "恢复数量不一致: backup={} backup_count={} restored={}".format(
                    source_name,
                    source_count,
                    restored,
                )
            )
        _log("[OK] backup={} count={} target={}".format(source_name, restored, target_name))

    return {
        "backup_tag": backup_tag,
        "pre_restore_tag": pre_restore_tag,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "collections": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="从备份集合恢复 JJC 身份治理相关 Mongo 集合")
    parser.add_argument("--tag", required=True, help="要恢复的备份标签，如 20260521_203000")
    parser.add_argument("--collections", default="default", help="逗号分隔集合名；默认恢复 JJC 身份相关集合")
    parser.add_argument("--pre-restore-tag", default="", help="恢复前备份标签；默认使用当前时间戳")
    parser.add_argument("--batch-size", type=int, default=1000, help="批量复制大小，默认 1000")
    parser.add_argument("--apply", action="store_true", help="真正执行恢复")
    parser.add_argument("--yes", action="store_true", help="与 --apply 同时使用，确认执行")
    args = parser.parse_args()

    if args.apply and not args.yes:
        raise SystemExit("--apply 需要同时传 --yes")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size 必须大于 0")

    uri = get_mongo_uri()
    db_name = get_db_name(uri)
    collections = parse_collections(args.collections)
    pre_restore_tag = args.pre_restore_tag.strip() or time.strftime("%Y%m%d_%H%M%S")

    client = MongoClient(uri)
    db = client[db_name]
    try:
        _log("[INFO] db={} backup_tag={} pre_restore_tag={} apply={} collections={}".format(
            db_name,
            args.tag,
            pre_restore_tag,
            args.apply,
            ",".join(collections),
        ))
        result = restore_collections(
            db,
            collections=collections,
            backup_tag=args.tag,
            pre_restore_tag=pre_restore_tag,
            apply=args.apply,
            batch_size=args.batch_size,
        )
        if args.apply:
            db[METADATA_COLLECTION].insert_one({
                **result,
                "type": "jjc_role_identity_restore",
                "db": db_name,
            })
            _log("[OK] metadata_collection={} backup_tag={} pre_restore_tag={}".format(
                METADATA_COLLECTION,
                args.tag,
                pre_restore_tag,
            ))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
