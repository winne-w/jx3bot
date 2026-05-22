#!/usr/bin/env python3
"""Normalize role_identities schema fields without changing identity profile values."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

SOURCE_INDICATOR = "indicator"
SOURCE_BACKFILL = "match_replay_indicator_backfill"
TIME_FIELDS = ("updated_at", "first_seen_at", "last_seen_at", "profile_observed_at", "created_at")
HISTORY_TIME_FIELDS = ("observed_at",)
EMPTY_HISTORY_VALUE = (None, "")


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


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def numeric_to_datetime(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return value


def normalize_history_entry(entry: Any) -> Tuple[Any, bool]:
    if not isinstance(entry, dict):
        return entry, False

    changed = False
    normalized: Dict[str, Any] = {}
    for key, value in entry.items():
        if value in EMPTY_HISTORY_VALUE:
            changed = True
            continue
        if key in HISTORY_TIME_FIELDS:
            new_value = numeric_to_datetime(value)
            if new_value is not value:
                changed = True
            value = new_value
        normalized[key] = value
    return normalized, changed


def normalize_profile_history(history: Any) -> Tuple[Any, bool]:
    if not isinstance(history, list):
        return history, False

    changed = False
    normalized: List[Any] = []
    for entry in history:
        new_entry, entry_changed = normalize_history_entry(entry)
        normalized.append(new_entry)
        changed = changed or entry_changed
    return normalized, changed


def build_normalize_update(doc: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """Return the Mongo update needed to normalize schema-only fields."""
    set_fields: Dict[str, Any] = {}
    reasons: Dict[str, str] = {}

    for field in TIME_FIELDS:
        if field not in doc:
            continue
        old_value = doc.get(field)
        new_value = numeric_to_datetime(old_value)
        if new_value is not old_value:
            set_fields[field] = new_value
            reasons[field] = "{}->datetime".format(type_name(old_value))

    if "profile_history" in doc:
        new_history, history_changed = normalize_profile_history(doc.get("profile_history"))
        if history_changed:
            set_fields["profile_history"] = new_history
            reasons["profile_history"] = "clean_empty_or_time_fields"

    if not set_fields:
        return None, reasons
    return {"$set": set_fields}, reasons


def build_query(source: str, identity_key: Optional[str] = None) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if source != "all":
        query["sources"] = source
    if identity_key:
        query["identity_key"] = identity_key
    return query


def summarize_types(docs: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    summary: Dict[str, Counter] = {}
    for doc in docs:
        for field in TIME_FIELDS:
            if field in doc:
                summary.setdefault(field, Counter())[type_name(doc.get(field))] += 1
        history = doc.get("profile_history")
        if isinstance(history, list):
            for entry in history:
                if isinstance(entry, dict) and "observed_at" in entry:
                    summary.setdefault("profile_history.observed_at", Counter())[type_name(entry.get("observed_at"))] += 1
    return {field: dict(counter) for field, counter in summary.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="规范化 role_identities schema 类型和 profile_history 空字段")
    parser.add_argument("--source", choices=[SOURCE_INDICATOR, SOURCE_BACKFILL, "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描多少条")
    parser.add_argument("--skip", type=int, default=0, help="跳过多少条")
    parser.add_argument("--identity-key", default=None, help="只处理指定 identity_key")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写库；默认行为")
    parser.add_argument("--apply", action="store_true", help="执行写库")
    parser.add_argument("--yes", action="store_true", help="与 --apply 配合确认写库")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.apply and not args.yes:
        raise SystemExit("--apply requires --yes")
    if args.limit is not None and args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.skip < 0:
        raise SystemExit("--skip must be >= 0")

    dry_run = not args.apply
    client = MongoClient(get_mongo_uri(), serverSelectionTimeoutMS=8000)
    db = client.get_default_database()
    collection = db.role_identities
    query = build_query(args.source, args.identity_key)
    cursor = collection.find(query).skip(int(args.skip or 0))
    if args.limit is not None:
        cursor = cursor.limit(int(args.limit))

    stats: Dict[str, Any] = {
        "dry_run": dry_run,
        "source": args.source,
        "scanned": 0,
        "needs_fix": 0,
        "updated": 0,
        "failed": 0,
        "reason_counts": {},
        "samples": [],
    }
    before_docs: List[Dict[str, Any]] = []
    after_docs: List[Dict[str, Any]] = []

    for doc in cursor:
        stats["scanned"] += 1
        before_docs.append(doc)
        update, reasons = build_normalize_update(doc)
        after_doc = dict(doc)
        if update is not None:
            stats["needs_fix"] += 1
            for key in reasons:
                reason_counts = stats["reason_counts"]
                reason_counts[key] = reason_counts.get(key, 0) + 1
            for key, value in update["$set"].items():
                after_doc[key] = value
            if len(stats["samples"]) < 10:
                stats["samples"].append({
                    "identity_key": doc.get("identity_key"),
                    "reasons": reasons,
                })
            if args.apply:
                try:
                    result = collection.update_one({"_id": doc["_id"]}, update)
                    if result.matched_count:
                        stats["updated"] += 1
                except Exception as exc:
                    stats["failed"] += 1
                    if len(stats["samples"]) < 10:
                        stats["samples"].append({
                            "identity_key": doc.get("identity_key"),
                            "error": str(exc),
                        })
        after_docs.append(after_doc)

    stats["type_summary_before"] = summarize_types(before_docs)
    stats["type_summary_after"] = summarize_types(after_docs)
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
