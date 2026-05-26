#!/usr/bin/env python3
"""Migrate legacy JJC sync queue rows to the identity-id queue.

The module is intentionally import-safe: MongoDB/config imports are only loaded
from CLI execution paths, while field mapping helpers are plain functions for
focused tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent

IDENTITY_SOURCE = "jjc_sync_identity_queue_migration"

IDENTITY_FIELDS = (
    "identity_key",
    "identity_level",
    "server",
    "name",
    "normalized_server",
    "normalized_name",
    "global_id",
    "global_role_id",
    "role_id",
    "game_role_id",
    "person_id",
    "zone",
    "identity_source",
    "role_info_observed_match_time",
    "role_info_source",
    "role_info_updated_at",
)

IDENTITY_PROFILE_FIELDS = tuple(field for field in IDENTITY_FIELDS if field != "identity_key")

QUEUE_STATE_FIELDS = (
    "source",
    "priority",
    "status",
    "queued_at",
    "queue_batch_id",
    "queue_mode",
    "queue_source",
    "priority_updated_at",
    "priority_updated_by",
    "interrupted_reason",
    "interrupted_at",
    "season_id",
    "season_start_time",
    "full_synced_until_time",
    "oldest_synced_match_time",
    "latest_seen_match_time",
    "history_exhausted",
    "last_cursor",
    "lease_owner",
    "lease_expires_at",
    "last_synced_at",
    "next_sync_after",
    "fail_count",
    "last_error",
    "created_at",
)

REVERSE_COPY_FIELDS = IDENTITY_FIELDS + QUEUE_STATE_FIELDS
IDENTITY_KEY_PREFIXES = ("global_id:", "global:", "game:", "name:")
RUNTIME_QUEUE_STATE_FIELDS = (
    "source",
    "status",
    "queued_at",
    "queue_batch_id",
    "queue_mode",
    "queue_source",
    "priority_updated_at",
    "priority_updated_by",
    "interrupted_reason",
    "interrupted_at",
    "season_id",
    "lease_owner",
    "lease_expires_at",
    "last_synced_at",
    "next_sync_after",
    "last_error",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_text(value: Any) -> str:
    return _text(value).lower()


def clean_optional(value: Any) -> Optional[str]:
    text = _text(value)
    return text or None


def first_present(*values: Any) -> Optional[str]:
    for value in values:
        text = clean_optional(value)
        if text:
            return text
    return None


def build_identity_key(
    global_id: Optional[str] = None,
    identity_key: Optional[str] = None,
    global_role_id: Optional[str] = None,
    zone: Optional[str] = None,
    game_role_id: Optional[str] = None,
    server: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[str, str]:
    """Build the preferred role identity key and level."""
    gid = clean_optional(global_id)
    if gid:
        return "global_id:%s" % gid, "global_id"

    sk01 = clean_optional(global_role_id)
    if sk01:
        return "global:%s" % sk01, "global"

    z = clean_optional(zone)
    rid = clean_optional(game_role_id)
    if z and rid:
        return "game:%s:%s" % (z, rid), "game_role"

    existing_key = clean_optional(identity_key)
    if existing_key:
        if existing_key.startswith("global_id:"):
            return existing_key, "global_id"
        if existing_key.startswith("global:"):
            return existing_key, "global"
        if existing_key.startswith("game:"):
            return existing_key, "game_role"
        if existing_key.startswith("name:"):
            return existing_key, "name"

    normalized_server = normalize_text(server)
    normalized_name = normalize_text(name)
    if normalized_server and normalized_name:
        return "name:%s:%s" % (normalized_server, normalized_name), "name"
    raise ValueError("legacy queue row has no usable identity anchor")


def has_identity_anchor(queue_doc: Dict[str, Any]) -> bool:
    if clean_optional(queue_doc.get("global_id")):
        return True
    identity_key = clean_optional(queue_doc.get("identity_key"))
    if identity_key and identity_key.startswith(IDENTITY_KEY_PREFIXES):
        return True
    if clean_optional(queue_doc.get("global_role_id")):
        return True
    if clean_optional(queue_doc.get("zone")) and first_present(queue_doc.get("game_role_id"), queue_doc.get("role_id")):
        return True
    server = first_present(queue_doc.get("normalized_server"), queue_doc.get("server"))
    name = first_present(queue_doc.get("normalized_name"), queue_doc.get("name"))
    return bool(server and name)


def legacy_identity_keys(queue_doc: Dict[str, Any]) -> List[str]:
    """Return candidate identity keys from strongest to weakest."""
    keys: List[str] = []
    global_id = clean_optional(queue_doc.get("global_id"))
    if global_id:
        keys.append("global_id:%s" % global_id)

    identity_key = clean_optional(queue_doc.get("identity_key"))
    global_role_id = clean_optional(queue_doc.get("global_role_id"))
    if global_role_id:
        keys.append("global:%s" % global_role_id)

    zone = clean_optional(queue_doc.get("zone"))
    role_id = first_present(queue_doc.get("game_role_id"), queue_doc.get("role_id"))
    if zone and role_id:
        keys.append("game:%s:%s" % (zone, role_id))

    server = first_present(queue_doc.get("normalized_server"), queue_doc.get("server"))
    name = first_present(queue_doc.get("normalized_name"), queue_doc.get("name"))
    if server or name:
        keys.append("name:%s:%s" % (normalize_text(server), normalize_text(name)))
    if identity_key and identity_key.startswith(IDENTITY_KEY_PREFIXES):
        keys.append(identity_key)

    deduped: List[str] = []
    for key in keys:
        if key not in deduped:
            deduped.append(key)
    return deduped


def identity_lookup_queries(queue_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build role_identities lookup queries in migration precedence order."""
    queries: List[Dict[str, Any]] = []

    global_id = clean_optional(queue_doc.get("global_id"))
    if global_id:
        queries.append({"$or": [{"global_id": global_id}, {"identity_key": "global_id:%s" % global_id}]})

    global_role_id = clean_optional(queue_doc.get("global_role_id"))
    if global_role_id:
        queries.append({
            "$or": [
                {"global_role_id": global_role_id},
                {"identity_key": "global:%s" % global_role_id},
            ]
        })

    zone = clean_optional(queue_doc.get("zone"))
    role_id = first_present(queue_doc.get("game_role_id"), queue_doc.get("role_id"))
    if zone and role_id:
        queries.append({
            "$or": [
                {"zone": zone, "game_role_id": role_id},
                {"zone": zone, "role_id": role_id},
                {"identity_key": "game:%s:%s" % (zone, role_id)},
            ]
        })

    server = first_present(queue_doc.get("normalized_server"), queue_doc.get("server"))
    name = first_present(queue_doc.get("normalized_name"), queue_doc.get("name"))
    if server or name:
        queries.append({
            "normalized_server": normalize_text(server),
            "normalized_name": normalize_text(name),
        })
    identity_key = clean_optional(queue_doc.get("identity_key"))
    if identity_key and identity_key.startswith(IDENTITY_KEY_PREFIXES):
        queries.append({"identity_key": identity_key})
    return queries


def build_identity_insert_doc(queue_doc: Dict[str, Any], now: float) -> Dict[str, Any]:
    """Create a minimal role_identities document from a legacy queue row."""
    if not has_identity_anchor(queue_doc):
        raise ValueError("legacy queue row has no usable identity anchor")
    game_role_id = first_present(queue_doc.get("game_role_id"), queue_doc.get("role_id"))
    identity_key, identity_level = build_identity_key(
        global_id=clean_optional(queue_doc.get("global_id")),
        identity_key=clean_optional(queue_doc.get("identity_key")),
        global_role_id=clean_optional(queue_doc.get("global_role_id")),
        zone=clean_optional(queue_doc.get("zone")),
        game_role_id=game_role_id,
        server=first_present(queue_doc.get("normalized_server"), queue_doc.get("server")),
        name=first_present(queue_doc.get("normalized_name"), queue_doc.get("name")),
    )
    now_dt = _utc_datetime(now)
    doc: Dict[str, Any] = {
        "identity_key": identity_key,
        "identity_level": identity_level,
        "sources": [IDENTITY_SOURCE],
        "aliases": legacy_identity_keys(queue_doc),
        "first_seen_at": now_dt,
        "last_seen_at": now_dt,
        "updated_at": now_dt,
    }
    copy_if_present(doc, queue_doc, IDENTITY_PROFILE_FIELDS)
    if game_role_id and not doc.get("game_role_id"):
        doc["game_role_id"] = game_role_id
    if not doc.get("normalized_server") and doc.get("server"):
        doc["normalized_server"] = normalize_text(doc.get("server"))
    if not doc.get("normalized_name") and doc.get("name"):
        doc["normalized_name"] = normalize_text(doc.get("name"))
    return doc


def copy_if_present(target: Dict[str, Any], source: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        if field in source and source.get(field) is not None:
            target[field] = source.get(field)


def merge_legacy_queue_docs(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
    preserve_existing_runtime_state: bool = False,
) -> Dict[str, Any]:
    """Merge duplicate legacy queue rows that resolve to the same identity."""
    merged = dict(existing)
    copy_if_present(merged, incoming, IDENTITY_PROFILE_FIELDS)
    if not preserve_existing_runtime_state:
        copy_if_present(merged, incoming, RUNTIME_QUEUE_STATE_FIELDS)
    if "created_at" not in merged and incoming.get("created_at") is not None:
        merged["created_at"] = incoming.get("created_at")
    for field in ("priority", "season_start_time", "full_synced_until_time", "latest_seen_match_time", "last_cursor", "fail_count"):
        current = existing.get(field)
        candidate = incoming.get(field)
        if candidate is not None and (current is None or candidate > current):
            merged[field] = candidate
    current_oldest = existing.get("oldest_synced_match_time")
    incoming_oldest = incoming.get("oldest_synced_match_time")
    if incoming_oldest is not None and (current_oldest is None or incoming_oldest < current_oldest):
        merged["oldest_synced_match_time"] = incoming_oldest
    if existing.get("history_exhausted") or incoming.get("history_exhausted"):
        merged["history_exhausted"] = True
    return merged


def build_identity_queue_update(
    old_queue_doc: Dict[str, Any],
    identity_doc: Dict[str, Any],
    now: float,
) -> Dict[str, Any]:
    """Build an upsert update for jjc_sync_identity_queue."""
    set_fields: Dict[str, Any] = {
        "identity_id": identity_doc["_id"],
        "updated_at": now,
    }
    copy_if_present(set_fields, identity_doc, IDENTITY_FIELDS)
    copy_if_present(set_fields, old_queue_doc, IDENTITY_PROFILE_FIELDS)
    copy_if_present(set_fields, old_queue_doc, QUEUE_STATE_FIELDS)

    set_on_insert = {
        "source": old_queue_doc.get("source") or IDENTITY_SOURCE,
        "status": old_queue_doc.get("status") or "pending",
        "next_sync_after": old_queue_doc.get("next_sync_after"),
        "fail_count": old_queue_doc.get("fail_count", 0),
        "last_cursor": old_queue_doc.get("last_cursor", 0),
        "created_at": old_queue_doc.get("created_at", now),
    }
    for field in list(set_on_insert.keys()):
        if field in set_fields:
            set_on_insert.pop(field, None)
    return {"$set": set_fields, "$setOnInsert": set_on_insert}


def build_reverse_role_queue_update(identity_queue_doc: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
    """Build an upsert update for rollback from identity queue to legacy key queue."""
    identity_key = clean_optional(identity_queue_doc.get("identity_key"))
    if not identity_key:
        return None

    set_fields: Dict[str, Any] = {"identity_key": identity_key, "updated_at": now}
    copy_if_present(set_fields, identity_queue_doc, REVERSE_COPY_FIELDS)
    set_fields.pop("identity_id", None)

    update = {
        "$set": set_fields,
        "$setOnInsert": {
            "source": identity_queue_doc.get("source") or "rollback_sync",
            "status": identity_queue_doc.get("status") or "pending",
            "next_sync_after": identity_queue_doc.get("next_sync_after"),
            "fail_count": identity_queue_doc.get("fail_count", 0),
            "last_cursor": identity_queue_doc.get("last_cursor", 0),
            "created_at": identity_queue_doc.get("created_at", now),
        },
    }
    for field in list(update["$setOnInsert"].keys()):
        if field in set_fields:
            update["$setOnInsert"].pop(field, None)
    return update


def should_skip_doc(doc: Dict[str, Any], include_syncing: bool) -> bool:
    return not include_syncing and doc.get("status") == "syncing"


def _utc_datetime(ts: float) -> Any:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc)


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

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
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


def get_db(mongo_uri: Optional[str], db_name: Optional[str]) -> Any:
    from pymongo import MongoClient

    client = MongoClient(mongo_uri or get_mongo_uri())
    if db_name:
        return client[db_name]
    default_db = client.get_default_database(default=None)
    if default_db is not None:
        return default_db
    return client["jx3bot"]


def find_identity_doc(db: Any, queue_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for query in identity_lookup_queries(queue_doc):
        doc = db.role_identities.find_one(query)
        if doc:
            return doc
    return None


def strongest_identity_fields(queue_doc: Dict[str, Any], now: float) -> Dict[str, Any]:
    doc = build_identity_insert_doc(queue_doc, now)
    doc.pop("_id", None)
    return doc


def maybe_upgrade_identity_doc(db: Any, identity_doc: Dict[str, Any], queue_doc: Dict[str, Any], now: float, dry_run: bool) -> Dict[str, Any]:
    """Promote a weaker matched identity to the strongest key available in the legacy row."""
    preferred = strongest_identity_fields(queue_doc, now)
    current_key = clean_optional(identity_doc.get("identity_key"))
    preferred_key = clean_optional(preferred.get("identity_key"))
    if not preferred_key or preferred_key == current_key:
        return identity_doc
    upgraded = dict(identity_doc)
    copy_if_present(upgraded, preferred, IDENTITY_FIELDS)
    aliases = list(upgraded.get("aliases") or [])
    if current_key and current_key not in aliases:
        aliases.append(current_key)
    for alias in preferred.get("aliases") or []:
        if alias not in aliases:
            aliases.append(alias)
    upgraded["aliases"] = aliases
    if not dry_run and identity_doc.get("_id") is not None:
        set_fields = {field: upgraded[field] for field in IDENTITY_FIELDS if field in upgraded}
        db.role_identities.update_one(
            {"_id": identity_doc["_id"]},
            {"$set": set_fields, "$addToSet": {"aliases": {"$each": aliases}}},
        )
    return upgraded


def resolve_or_create_identity(db: Any, queue_doc: Dict[str, Any], now: float, dry_run: bool) -> Tuple[Optional[Dict[str, Any]], str]:
    if not has_identity_anchor(queue_doc):
        return None, "unresolvable"
    doc = find_identity_doc(db, queue_doc)
    if doc:
        return maybe_upgrade_identity_doc(db, doc, queue_doc, now, dry_run), "resolved"
    insert_doc = build_identity_insert_doc(queue_doc, now)
    if dry_run:
        preview = dict(insert_doc)
        preview["_id"] = "dry-run-%s" % hashlib.sha1(
            preview["identity_key"].encode("utf-8")
        ).hexdigest()[:16]
        return preview, "create"
    result = db.role_identities.insert_one(insert_doc)
    insert_doc["_id"] = result.inserted_id
    return insert_doc, "created"


def migrate_forward(args: argparse.Namespace) -> Dict[str, int]:
    db = get_db(args.mongo_uri, args.db_name)
    query: Dict[str, Any] = {}
    if not args.include_syncing:
        query["status"] = {"$ne": "syncing"}
    if args.after_id:
        from bson import ObjectId

        query["_id"] = {"$gt": ObjectId(args.after_id)}

    cursor = db.jjc_sync_role_queue.find(query).sort([("_id", 1)])
    if args.limit:
        cursor = cursor.limit(args.limit)

    dry_run = not args.execute or args.dry_run
    stats = {
        "seen": 0,
        "skipped": 0,
        "unresolvable": 0,
        "duplicates": 0,
        "resolved": 0,
        "created": 0,
        "upserted": 0,
        "dry_run": 0,
        "failed": 0,
    }
    merged_by_identity: Dict[str, Dict[str, Any]] = {}
    for old_doc in cursor:
        stats["seen"] += 1
        if should_skip_doc(old_doc, args.include_syncing):
            stats["skipped"] += 1
            continue
        now = time.time()
        try:
            identity_doc, action = resolve_or_create_identity(db, old_doc, now, dry_run)
            if identity_doc is None:
                stats["unresolvable"] += 1
                if args.verbose:
                    _log("skip unresolvable identity_key=%s" % old_doc.get("identity_key"))
                continue
            stats["created" if action in ("create", "created") else "resolved"] += 1
            identity_id_key = str(identity_doc.get("_id"))
            merged_doc = old_doc
            if identity_id_key in merged_by_identity:
                stats["duplicates"] += 1
                merged_doc = merge_legacy_queue_docs(merged_by_identity[identity_id_key], old_doc)
            elif not dry_run:
                existing_queue = db.jjc_sync_identity_queue.find_one({"identity_id": identity_doc["_id"]})
                if existing_queue:
                    stats["duplicates"] += 1
                    merged_doc = merge_legacy_queue_docs(
                        existing_queue,
                        old_doc,
                        preserve_existing_runtime_state=True,
                    )
            merged_by_identity[identity_id_key] = merged_doc
            update = build_identity_queue_update(merged_doc, identity_doc, now)
            if args.verbose:
                _log("migrate identity_key=%s identity_id=%s action=%s status=%s" % (
                    old_doc.get("identity_key"),
                    identity_doc.get("_id"),
                    action,
                    old_doc.get("status"),
                ))
            if dry_run:
                stats["dry_run"] += 1
                continue
            db.jjc_sync_identity_queue.update_one({"identity_id": identity_doc["_id"]}, update, upsert=True)
            stats["upserted"] += 1
        except Exception as exc:
            stats["failed"] += 1
            _log("failed identity_key=%s error=%s" % (old_doc.get("identity_key"), exc))
    return stats


def migrate_reverse(args: argparse.Namespace) -> Dict[str, int]:
    db = get_db(args.mongo_uri, args.db_name)
    query: Dict[str, Any] = {"identity_key": {"$exists": True, "$ne": ""}}
    if not args.include_syncing:
        query["status"] = {"$ne": "syncing"}
    if args.after_id:
        from bson import ObjectId

        query["_id"] = {"$gt": ObjectId(args.after_id)}

    cursor = db.jjc_sync_identity_queue.find(query).sort([("_id", 1)])
    if args.limit:
        cursor = cursor.limit(args.limit)

    dry_run = not args.execute or args.dry_run
    stats = {"seen": 0, "skipped": 0, "upserted": 0, "dry_run": 0, "failed": 0}
    for new_doc in cursor:
        stats["seen"] += 1
        if should_skip_doc(new_doc, args.include_syncing):
            stats["skipped"] += 1
            continue
        now = time.time()
        update = build_reverse_role_queue_update(new_doc, now)
        if update is None:
            stats["skipped"] += 1
            continue
        identity_key = update["$set"]["identity_key"]
        if args.verbose:
            _log("reverse identity_key=%s identity_id=%s status=%s" % (
                identity_key,
                new_doc.get("identity_id"),
                new_doc.get("status"),
            ))
        if dry_run:
            stats["dry_run"] += 1
            continue
        try:
            db.jjc_sync_role_queue.update_one({"identity_key": identity_key}, update, upsert=True)
            stats["upserted"] += 1
        except Exception as exc:
            stats["failed"] += 1
            _log("reverse failed identity_key=%s error=%s" % (identity_key, exc))
    return stats


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate JJC sync queue to identity-id queue")
    subparsers = parser.add_subparsers(dest="command")

    forward = subparsers.add_parser("forward", help="migrate old jjc_sync_role_queue to jjc_sync_identity_queue")
    add_common_args(forward)
    forward.set_defaults(func=migrate_forward)

    reverse = subparsers.add_parser("reverse-sync", help="sync identity queue rows back to old identity_key queue")
    add_common_args(reverse)
    reverse.set_defaults(func=migrate_reverse)
    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI; default reads runtime_config/config/env")
    parser.add_argument("--db-name", default=None, help="MongoDB database name when URI has no default DB")
    parser.add_argument("--dry-run", action="store_true", help="show intended work without writes; this is also the default")
    parser.add_argument("--execute", action="store_true", help="perform writes; omitted means dry-run")
    parser.add_argument("--limit", type=int, default=0, help="maximum rows to process")
    parser.add_argument("--after-id", default=None, help="only process source rows with _id greater than this ObjectId")
    parser.add_argument("--include-syncing", action="store_true", help="include rows with status=syncing")
    parser.add_argument("--verbose", action="store_true", help="print each processed row")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    argv_list = list(argv if argv is not None else sys.argv[1:])
    if not argv_list:
        parser.print_help()
        return 2
    args = parser.parse_args(argv_list)
    stats = args.func(args)
    print(" ".join("%s=%s" % (key, stats[key]) for key in sorted(stats)))
    return 0 if stats.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
