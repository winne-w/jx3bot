#!/usr/bin/env python3
"""Audit JJC role identities against person-history role-level evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.jx3.jjc_match_data_sync import (  # noqa: E402
    extract_history_items,
    normalize_role_name,
)
from src.services.jx3.tuilan_rate_limit import random_sleep  # noqa: E402


COLLECTIONS = ("role_identities", "jjc_sync_role_queue")
REPORT_CATEGORIES = (
    "confirmed_valid",
    "confirmed_dirty",
    "suspected_dirty",
    "unknown",
    "api_failed",
    "conflict_needs_manual_merge",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_key(value: Any) -> str:
    return _text(value).lower()


def _expected_fields(doc: Dict[str, Any]) -> Dict[str, str]:
    server = _text(doc.get("server"))
    name = _text(doc.get("role_name") or doc.get("name"))
    role_id = _text(doc.get("role_id") or doc.get("game_role_id"))
    return {
        "person_id": _text(doc.get("person_id")),
        "global_role_id": _text(doc.get("global_role_id")),
        "zone": _text(doc.get("zone")),
        "role_id": role_id,
        "server": server,
        "role_name": normalize_role_name(name, server) if server and name else name,
    }


def _candidate_fields(item: Dict[str, Any]) -> Dict[str, str]:
    server = _text(item.get("server"))
    return {
        "person_id": _text(item.get("person_id")),
        "global_role_id": _text(item.get("global_role_id") or item.get("globalRoleId")),
        "zone": _text(item.get("zone")),
        "role_id": _text(item.get("role_id") or item.get("roleId")),
        "server": server,
        "role_name": normalize_role_name(
            item.get("role_name") or item.get("roleName"),
            server,
        ),
    }


def role_fields_match(expected: Dict[str, str], candidate: Dict[str, str]) -> bool:
    if (
        expected.get("zone")
        and expected.get("role_id")
        and candidate.get("zone")
        and candidate.get("role_id")
        and expected["zone"] == candidate["zone"]
        and expected["role_id"] == candidate["role_id"]
    ):
        return True
    if (
        expected.get("server")
        and expected.get("role_name")
        and candidate.get("server")
        and candidate.get("role_name")
        and expected["server"] == candidate["server"]
        and expected["role_name"] == candidate["role_name"]
    ):
        return True
    return False


def role_fields_conflict(expected: Dict[str, str], candidate: Dict[str, str]) -> bool:
    if (
        expected.get("zone")
        and expected.get("role_id")
        and candidate.get("zone")
        and candidate.get("role_id")
        and (expected["zone"] != candidate["zone"] or expected["role_id"] != candidate["role_id"])
    ):
        return True
    if (
        expected.get("server")
        and expected.get("role_name")
        and candidate.get("server")
        and candidate.get("role_name")
        and (expected["server"] != candidate["server"] or expected["role_name"] != candidate["role_name"])
    ):
        return True
    return False


def build_degraded_identity_key(doc: Dict[str, Any]) -> Tuple[str, str]:
    zone = _text(doc.get("zone"))
    role_id = _text(doc.get("role_id") or doc.get("game_role_id"))
    if zone and role_id:
        return "game:{}:{}".format(zone, role_id), "game_role"

    server = _text(doc.get("normalized_server")) or _normalized_key(doc.get("server"))
    name = _text(doc.get("normalized_name"))
    if not name:
        raw_name = _text(doc.get("role_name") or doc.get("name"))
        raw_server = _text(doc.get("server"))
        if raw_name and raw_server:
            name = normalize_role_name(raw_name, raw_server).lower()
        else:
            name = raw_name.lower()
    if server and name:
        return "name:{}:{}".format(server, name), "name"
    return "", ""


def build_repair_update(
    doc: Dict[str, Any],
    collection: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    repaired_at = now or datetime.now(timezone.utc)
    new_key, identity_level = build_degraded_identity_key(doc)
    if not new_key:
        return {}

    set_fields: Dict[str, Any] = {
        "identity_key": new_key,
        "identity_source": "person_history_mismatch_cleaned",
        "updated_at": repaired_at,
        "person_history_audit": {
            "action": "clear_mismatched_global_role_id",
            "original_identity_key": _text(doc.get("identity_key")),
            "original_global_role_id": _text(doc.get("global_role_id")),
            "repaired_at": repaired_at.isoformat(),
        },
    }
    if collection == "role_identities":
        set_fields["identity_level"] = identity_level
    if collection == "jjc_sync_role_queue":
        set_fields.update({
            "status": "pending",
            "full_synced_until_time": None,
            "oldest_synced_match_time": None,
            "latest_seen_match_time": None,
            "history_exhausted": None,
            "lease_owner": None,
            "lease_expires_at": None,
            "fail_count": 0,
            "last_cursor": 0,
            "next_sync_after": None,
        })

    return {
        "$set": set_fields,
        "$unset": {"global_role_id": ""},
    }


def classify_identity_doc(
    doc: Dict[str, Any],
    payload: Dict[str, Any],
    collection: str,
    target_key_exists: bool = False,
    api_error: bool = False,
) -> Dict[str, Any]:
    expected = _expected_fields(doc)
    base: Dict[str, Any] = {
        "collection": collection,
        "identity_key": _text(doc.get("identity_key")),
        "person_id": expected["person_id"],
        "global_role_id": expected["global_role_id"],
    }
    if api_error or not isinstance(payload, dict) or payload.get("error"):
        base.update({"category": "api_failed", "reason": _text(payload.get("error") if isinstance(payload, dict) else "")})
        return base

    same_person: List[Dict[str, str]] = []
    same_global: List[Dict[str, str]] = []
    for item in extract_history_items(payload):
        candidate = _candidate_fields(item)
        if expected["person_id"] and candidate["person_id"] and candidate["person_id"] != expected["person_id"]:
            continue
        same_person.append(candidate)
        if candidate["global_role_id"] == expected["global_role_id"]:
            same_global.append(candidate)

    base["candidate_count"] = len(same_person)
    base["same_global_count"] = len(same_global)

    for candidate in same_global:
        if role_fields_match(expected, candidate):
            base.update({"category": "confirmed_valid", "reason": "role_fields_match", "candidate": candidate})
            return base

    dirty_candidate: Optional[Dict[str, str]] = None
    for candidate in same_global:
        if role_fields_conflict(expected, candidate):
            dirty_candidate = candidate
            break

    if dirty_candidate:
        repair_update = build_repair_update(doc, collection)
        new_key = _text(repair_update.get("$set", {}).get("identity_key"))
        category = "conflict_needs_manual_merge" if target_key_exists else "confirmed_dirty"
        base.update({
            "category": category,
            "reason": "same_global_role_id_role_fields_conflict",
            "candidate": dirty_candidate,
            "repair_identity_key": new_key,
        })
        return base

    if not same_global and same_person:
        base.update({"category": "suspected_dirty", "reason": "global_role_id_not_found_for_person"})
        return base

    base.update({"category": "unknown", "reason": "insufficient_person_history_evidence"})
    return base


def ensure_apply_allowed(apply: bool, yes: bool) -> None:
    if apply and not yes:
        raise ValueError("--apply requires --yes")


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


def _collection_names(value: str) -> List[str]:
    if value == "all":
        return list(COLLECTIONS)
    return [value]


def _base_filter(args: argparse.Namespace) -> Dict[str, Any]:
    query: Dict[str, Any] = {
        "person_id": {"$exists": True, "$nin": ["", None]},
        "global_role_id": {"$exists": True, "$nin": ["", None]},
    }
    if args.person_id:
        query["person_id"] = args.person_id
    if args.global_role_id:
        query["global_role_id"] = args.global_role_id
    return query


def _matches_expected_role(item: Dict[str, Any], expected: Dict[str, str]) -> bool:
    candidate = _candidate_fields(item)
    if expected.get("person_id") and candidate.get("person_id") and candidate["person_id"] != expected["person_id"]:
        return False
    return role_fields_match(expected, candidate)


async def _fetch_payload(
    client: Any,
    person_id: str,
    expected: Optional[Dict[str, str]] = None,
    page_size: int = 20,
    sleep_func: Callable[[], Awaitable[None]] = random_sleep,
) -> Dict[str, Any]:
    cursor = 0
    all_items: List[Dict[str, Any]] = []
    while True:
        if cursor > 0:
            await sleep_func()
        payload = await asyncio.to_thread(
            client.get_person_match_history,
            person_id=person_id,
            size=page_size,
            cursor=cursor,
        )
        if not isinstance(payload, dict) or payload.get("error"):
            return payload if isinstance(payload, dict) else {"error": "invalid_person_history_response"}
        items = extract_history_items(payload)
        if not items:
            return {"data": all_items}
        all_items.extend(items)
        if expected and any(_matches_expected_role(item, expected) for item in items):
            return {"data": all_items}
        cursor += page_size


async def run_audit(
    db: Any,
    person_history_client: Any,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    ensure_apply_allowed(bool(args.apply), bool(args.yes))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = ROOT / "data" / "jjc_identity_audit" / timestamp
    details_dir = report_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    details: Dict[str, List[Dict[str, Any]]] = {category: [] for category in REPORT_CATEGORIES}
    query = _base_filter(args)
    applied = 0

    for collection in _collection_names(args.collection):
        cursor = db[collection].find(query)
        if args.limit:
            cursor = cursor.limit(int(args.limit))
        docs = await cursor.to_list(length=args.limit or None)
        for doc in docs:
            person_id = _text(doc.get("person_id"))
            try:
                payload = await _fetch_payload(
                    person_history_client,
                    person_id,
                    expected=_expected_fields(doc),
                )
                api_error = not isinstance(payload, dict) or bool(payload.get("error"))
            except Exception as exc:
                payload = {"error": str(exc)}
                api_error = True

            repair_update = build_repair_update(doc, collection)
            repair_key = _text(repair_update.get("$set", {}).get("identity_key"))
            target_key_exists = False
            if repair_key:
                conflict = await db[collection].find_one({
                    "identity_key": repair_key,
                    "_id": {"$ne": doc.get("_id")},
                })
                target_key_exists = conflict is not None

            result = classify_identity_doc(
                doc,
                payload if isinstance(payload, dict) else {},
                collection,
                target_key_exists=target_key_exists,
                api_error=api_error,
            )
            if result["category"] == "confirmed_dirty" and repair_update:
                result["repair_update"] = repair_update
                if args.apply:
                    await db[collection].update_one({"_id": doc.get("_id")}, repair_update)
                    applied += 1
            details[result["category"]].append(result)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": not bool(args.apply),
        "applied": applied,
        "counts": {category: len(items) for category, items in details.items()},
    }
    for category, items in details.items():
        with open(str(details_dir / "{}.json".format(category)), "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2, default=str)
    with open(str(report_dir / "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)
    summary["report_path"] = str(report_dir / "summary.json")
    return summary


async def main_async(args: argparse.Namespace) -> int:
    ensure_apply_allowed(bool(args.apply), bool(args.yes))
    from motor.motor_asyncio import AsyncIOMotorClient

    import config as cfg
    from src.services.jx3.match_history import PersonMatchHistoryClient
    from src.utils.tuilan_request import tuilan_request

    uri = get_mongo_uri()
    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    client = AsyncIOMotorClient(uri, maxPoolSize=10, serverSelectionTimeoutMS=5000)
    await client.admin.command("ping")
    db = client[db_name]
    person_history_client = PersonMatchHistoryClient(
        person_match_history_url=cfg.API_URLS["竞技场个人战局历史"],
        tuilan_request=tuilan_request,
    )
    summary = await run_audit(db, person_history_client, args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="审计 JJC person-history 身份错绑")
    parser.add_argument("--collection", choices=("role_identities", "jjc_sync_role_queue", "all"), default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--person-id", default="")
    parser.add_argument("--global-role-id", default="")
    parser.add_argument("--apply", action="store_true", help="执行明确脏数据修复")
    parser.add_argument("--yes", action="store_true", help="与 --apply 配合确认写库")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return asyncio.run(main_async(args))
    except ValueError as exc:
        print("错误: {}".format(exc))
        return 2
    except Exception as exc:
        print("审计失败: {}".format(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
