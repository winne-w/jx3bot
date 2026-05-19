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


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _format_expected(expected: Dict[str, str]) -> str:
    role = "{}/{}".format(expected.get("server") or "-", expected.get("role_name") or "-")
    return "{} person_id={} global_role_id={}".format(
        role,
        expected.get("person_id") or "-",
        expected.get("global_role_id") or "-",
    )


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
            "audited_at": repaired_at.isoformat(),
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


def find_expected_role_candidate(payload: Dict[str, Any], expected: Dict[str, str]) -> Optional[Dict[str, str]]:
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    for item in extract_history_items(payload):
        candidate = _candidate_fields(item)
        if expected["person_id"] and candidate["person_id"] and candidate["person_id"] != expected["person_id"]:
            continue
        if role_fields_match(expected, candidate) and candidate.get("global_role_id"):
            return candidate
    return None


def build_correct_global_repair_update(
    doc: Dict[str, Any],
    collection: str,
    candidate: Optional[Dict[str, str]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if not candidate:
        return {}
    global_role_id = _text(candidate.get("global_role_id"))
    if not global_role_id:
        return {}

    repaired_at = now or datetime.now(timezone.utc)
    identity_key = "global:{}".format(global_role_id)
    server = _text(candidate.get("server")) or _text(doc.get("server"))
    role_name = _text(candidate.get("role_name")) or _text(doc.get("role_name") or doc.get("name"))
    role_id = _text(candidate.get("role_id")) or _text(doc.get("role_id") or doc.get("game_role_id"))
    zone = _text(candidate.get("zone")) or _text(doc.get("zone"))

    set_fields: Dict[str, Any] = {
        "identity_key": identity_key,
        "global_role_id": global_role_id,
        "identity_source": "person_history_corrected_global_role_id",
        "updated_at": repaired_at,
        "person_history_audit": {
            "action": "replace_mismatched_global_role_id",
            "original_identity_key": _text(doc.get("identity_key")),
            "original_global_role_id": _text(doc.get("global_role_id")),
            "corrected_identity_key": identity_key,
            "corrected_global_role_id": global_role_id,
            "repaired_at": repaired_at.isoformat(),
            "audited_at": repaired_at.isoformat(),
        },
    }
    if collection == "role_identities":
        set_fields["identity_level"] = "global"
    if server:
        set_fields["server"] = server
        set_fields["normalized_server"] = server.lower()
    if role_name:
        set_fields["name"] = role_name
        set_fields["role_name"] = role_name
        set_fields["normalized_name"] = role_name.lower()
    if zone:
        set_fields["zone"] = zone
    if role_id:
        set_fields["role_id"] = role_id
        set_fields["game_role_id"] = role_id
    if _text(doc.get("person_id")):
        set_fields["person_id"] = _text(doc.get("person_id"))

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

    return {"$set": set_fields}


async def _mark_audited(db: Any, collection: str, doc_id: Any, now: Optional[datetime] = None) -> None:
    """标记文档已审计，用于断点续跑。"""
    ts = (now or datetime.now(timezone.utc)).isoformat()
    await db[collection].update_one(
        {"_id": doc_id},
        {"$set": {"person_history_audit.audited_at": ts}},
    )


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
    correct_candidate: Optional[Dict[str, str]] = None
    for item in extract_history_items(payload):
        candidate = _candidate_fields(item)
        if expected["person_id"] and candidate["person_id"] and candidate["person_id"] != expected["person_id"]:
            continue
        same_person.append(candidate)
        if correct_candidate is None and role_fields_match(expected, candidate) and candidate.get("global_role_id"):
            correct_candidate = candidate
        if candidate["global_role_id"] == expected["global_role_id"]:
            same_global.append(candidate)

    base["candidate_count"] = len(same_person)
    base["same_global_count"] = len(same_global)

    for candidate in same_global:
        if role_fields_match(expected, candidate):
            base.update({"category": "confirmed_valid", "reason": "role_fields_match", "candidate": candidate})
            return base

    if (
        correct_candidate
        and expected.get("global_role_id")
        and correct_candidate.get("global_role_id")
        and correct_candidate["global_role_id"] != expected["global_role_id"]
    ):
        new_key = "global:{}".format(correct_candidate["global_role_id"])
        category = "conflict_needs_manual_merge" if target_key_exists else "confirmed_dirty"
        base.update({
            "category": category,
            "reason": "expected_role_has_different_global_role_id",
            "correct_candidate": correct_candidate,
            "repair_identity_key": new_key,
        })
        return base

    dirty_candidate: Optional[Dict[str, str]] = None
    for candidate in same_global:
        if role_fields_conflict(expected, candidate):
            dirty_candidate = candidate
            break

    if dirty_candidate:
        new_key = "global:{}".format(correct_candidate["global_role_id"]) if correct_candidate else ""
        category = "conflict_needs_manual_merge" if target_key_exists else "confirmed_dirty"
        base.update({
            "category": category,
            "reason": "same_global_role_id_role_fields_conflict",
            "candidate": dirty_candidate,
            "repair_identity_key": new_key,
        })
        if correct_candidate:
            base["correct_candidate"] = correct_candidate
        else:
            base["reason"] = "same_global_role_id_conflicts_but_correct_role_not_found"
        return base

    if not same_global and same_person:
        base.update({"category": "suspected_dirty", "reason": "global_role_id_not_found_for_person"})
        return base

    base.update({"category": "unknown", "reason": "insufficient_person_history_evidence"})
    return base


def ensure_apply_allowed(apply: bool, yes: bool) -> None:
    if apply and not yes:
        raise ValueError("--apply requires --yes")


def normalize_repair_flags(args: argparse.Namespace) -> None:
    if bool(getattr(args, "repair", False)):
        args.apply = True
        args.yes = True


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


def _append_and(query: Dict[str, Any], condition: Dict[str, Any]) -> None:
    existing = query.pop("$and", [])
    if not isinstance(existing, list):
        existing = [existing]
    existing.append(condition)
    query["$and"] = existing


def _base_filter(args: argparse.Namespace) -> Dict[str, Any]:
    query: Dict[str, Any] = {
        "person_id": {"$exists": True, "$nin": ["", None]},
        "global_role_id": {"$exists": True, "$nin": ["", None]},
    }
    if not getattr(args, "reprocess", False):
        query["person_history_audit.audited_at"] = {"$exists": False}
    if args.person_id:
        query["person_id"] = args.person_id
    if args.global_role_id:
        query["global_role_id"] = args.global_role_id
    server = _text(getattr(args, "server", ""))
    name = _text(getattr(args, "name", ""))
    if server:
        _append_and(query, {
            "$or": [
                {"server": server},
                {"normalized_server": server.lower()},
            ]
        })
    if name:
        normalized_name = normalize_role_name(name, server).lower() if server else name.lower()
        _append_and(query, {
            "$or": [
                {"name": name},
                {"role_name": name},
                {"normalized_name": normalized_name},
            ]
        })
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


async def discover_new_roles_from_person_history(
    db: Any,
    payload: Dict[str, Any],
    person_id: str,
) -> int:
    """从 person-history 响应中发现未收录的角色，补录到 role_identities 和 jjc_sync_role_queue。"""
    if not isinstance(payload, dict) or not person_id:
        return 0
    items = extract_history_items(payload)
    if not items:
        return 0

    seen: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for item in items:
        candidate = _candidate_fields(item)
        gid = candidate.get("global_role_id")
        if not gid:
            continue
        key = (gid, candidate.get("server") or "", candidate.get("role_name") or "")
        if key not in seen:
            seen[key] = candidate

    discovered = 0
    now = datetime.now(timezone.utc)
    for (gid, server, name), candidate in seen.items():
        exists = await db.role_identities.find_one({
            "$or": [
                {"global_role_id": gid},
                {
                    "zone": candidate.get("zone"),
                    "game_role_id": candidate.get("role_id"),
                    "zone": {"$ne": ""},
                    "game_role_id": {"$ne": ""},
                },
            ],
        })
        if exists:
            continue
        normalized_server = server.lower()
        normalized_name = name.lower()
        identity_doc = {
            "identity_key": "global:{}".format(gid),
            "identity_level": "global",
            "global_role_id": gid,
            "person_id": candidate.get("person_id") or person_id,
            "server": server,
            "normalized_server": normalized_server,
            "name": name,
            "role_name": name,
            "normalized_name": normalized_name,
            "zone": candidate.get("zone") or "",
            "role_id": candidate.get("role_id") or "",
            "game_role_id": candidate.get("role_id") or "",
            "identity_source": "person_history_discovered",
            "first_seen_at": now,
            "last_seen_at": now,
            "updated_at": now,
        }
        await db.role_identities.insert_one(identity_doc)
        queue_doc = {
            "identity_key": "global:{}".format(gid),
            "identity_level": "global",
            "global_role_id": gid,
            "person_id": candidate.get("person_id") or person_id,
            "server": server,
            "normalized_server": normalized_server,
            "name": name,
            "role_name": name,
            "normalized_name": normalized_name,
            "zone": candidate.get("zone") or "",
            "role_id": candidate.get("role_id") or "",
            "game_role_id": candidate.get("role_id") or "",
            "identity_source": "person_history_discovered",
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
            "first_seen_at": now,
            "last_seen_at": now,
            "updated_at": now,
        }
        await db.jjc_sync_role_queue.insert_one(queue_doc)
        _log("[DISCOVER] person_id={} server={} name={} global_role_id={} 已补录到 role_identities + jjc_sync_role_queue".format(
            person_id, server, name, gid,
        ))
        discovered += 1
    return discovered


def _doc_normalized_server(doc: Dict[str, Any]) -> str:
    return _text(doc.get("normalized_server")) or _text(doc.get("server")).lower()


def _doc_normalized_name(doc: Dict[str, Any]) -> str:
    return _text(doc.get("normalized_name")) or _text(doc.get("role_name") or doc.get("name")).lower()


def detect_same_role_duplicates(
    all_items: List[Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any], int, int]],
) -> List[Tuple[str, List[Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any], int, int]]]]:
    """检测同 collection 内同 server+name 的多条文档组，且组内存在不一致。"""
    groups: Dict[Tuple[str, str, str], List[
        Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any], int, int]
    ]] = {}
    for item in all_items:
        collection, doc, repair_update, result, index, process_count = item
        ns = _doc_normalized_server(doc)
        nn = _doc_normalized_name(doc)
        if not ns or not nn:
            continue
        key = (collection, ns, nn)
        groups.setdefault(key, []).append(item)

    duplicates = []
    for (collection, ns, nn), group in groups.items():
        if len(group) < 2:
            continue
        has_issue = any(
            result["category"] in ("confirmed_dirty", "conflict_needs_manual_merge")
            for _, _, _, result, _, _ in group
        )
        if has_issue:
            duplicates.append((collection, group))
    return duplicates


async def resolve_duplicate_merge(
    db: Any,
    collection: str,
    group_items: List[Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any], int, int]],
    match_history_client: Any,
) -> Tuple[int, List[Dict[str, Any]]]:
    """合并同角色重复文档：match history 交叉验证后，保留 person-history 中出现的，归档旧的。"""
    merged = 0
    merged_details: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    gids = []
    for _, doc, _, _, _, _ in group_items:
        gid = _text(doc.get("global_role_id"))
        if gid and gid not in gids:
            gids.append(gid)
    if len(gids) < 2:
        return 0, []

    # match history 交叉验证
    match_ids: Dict[str, List[str]] = {}
    for gid in gids:
        try:
            payload = await asyncio.to_thread(
                match_history_client.get_mine_match_history,
                global_role_id=gid,
                size=2,
                cursor=0,
            )
            items = extract_history_items(payload) if isinstance(payload, dict) else []
            match_ids[gid] = [
                _text(item.get("match_id") or item.get("id") or item.get("matchId"))
                for item in items[:2]
            ]
        except Exception:
            match_ids[gid] = []

    all_match_sets = [set(mids) for mids in match_ids.values() if mids]
    verified = False
    if len(all_match_sets) >= 2:
        verified = bool(all_match_sets[0] & all_match_sets[1])
    if not verified:
        _log("[MERGE_SKIP] collection={} server={} name={} match history 验证失败，跳过合并".format(
            collection,
            _text(group_items[0][1].get("server") or group_items[0][1].get("name")),
            _text(group_items[0][1].get("role_name") or group_items[0][1].get("name")),
        ))
        return 0, []

    # 确定保留/归档
    gid_in_person_history: set = set()
    for _, doc, _, result, _, _ in group_items:
        correct = result.get("correct_candidate")
        if correct and correct.get("global_role_id"):
            gid_in_person_history.add(_text(correct.get("global_role_id")))
        elif result.get("category") == "confirmed_valid":
            gid_in_person_history.add(_text(doc.get("global_role_id")))

    keep_items = []
    archive_items = []
    for item in group_items:
        _, doc, _, _, _, _ = item
        gid = _text(doc.get("global_role_id"))
        if gid in gid_in_person_history:
            keep_items.append(item)
        else:
            archive_items.append(item)

    if not keep_items:
        keep_items = [archive_items.pop(0)]

    # 归档旧文档
    for _, doc, _, _, _, _ in archive_items:
        archive_doc = dict(doc)
        archive_doc.pop("_id", None)
        archive_doc["archived_at"] = now
        archive_doc["archive_reason"] = "duplicate_global_role_id_merged"
        archive_doc["replaced_by_identity_key"] = _text(keep_items[0][1].get("identity_key"))
        try:
            await db.role_identities_history.insert_one(archive_doc)
            await db[collection].delete_one({"_id": doc.get("_id")})
            _log("[MERGE] collection={} server={} name={} archive: identity_key={} gid={} role_id={} -> 已归档".format(
                collection,
                _text(doc.get("server") or doc.get("name")),
                _text(doc.get("role_name") or doc.get("name")),
                _text(doc.get("identity_key")),
                _text(doc.get("global_role_id")),
                _text(doc.get("role_id") or doc.get("game_role_id")),
            ))
            merged += 1
            merged_details.append({
                "collection": collection,
                "action": "archive",
                "archived_identity_key": _text(doc.get("identity_key")),
                "archived_global_role_id": _text(doc.get("global_role_id")),
                "replaced_by": _text(keep_items[0][1].get("identity_key")),
            })
        except Exception as exc:
            _log("[MERGE_FAIL] collection={} identity_key={} 归档失败: {}".format(
                collection, _text(doc.get("identity_key")), exc,
            ))

    # 补全保留文档缺失的 role_id / zone
    keep_collection, keep_doc, _, keep_result, _, _ = keep_items[0]
    missing_fields: Dict[str, str] = {}
    if not _text(keep_doc.get("role_id") or keep_doc.get("game_role_id")):
        for _, arch_doc, _, _, _, _ in archive_items:
            rid = _text(arch_doc.get("role_id") or arch_doc.get("game_role_id"))
            if rid:
                missing_fields["role_id"] = rid
                missing_fields["game_role_id"] = rid
                break
    if not _text(keep_doc.get("zone")):
        for _, arch_doc, _, _, _, _ in archive_items:
            z = _text(arch_doc.get("zone"))
            if z:
                missing_fields["zone"] = z
                break
    if missing_fields:
        try:
            await db[keep_collection].update_one(
                {"_id": keep_doc.get("_id")},
                {"$set": missing_fields},
            )
            _log("[MERGE] collection={} identity_key={} 从归档文档补全字段: {}".format(
                keep_collection,
                _text(keep_doc.get("identity_key")),
                json.dumps(missing_fields, ensure_ascii=False),
            ))
        except Exception as exc:
            _log("[MERGE_FAIL] collection={} identity_key={} 补全字段失败: {}".format(
                keep_collection, _text(keep_doc.get("identity_key")), exc,
            ))

    return merged, merged_details


async def _resolve_conflict_chain(
    db: Any,
    person_history_client: Any,
    match_history_client: Any,
    collection: str,
    doc: Dict[str, Any],
    repair_update: Dict[str, Any],
    result: Dict[str, Any],
    args: argparse.Namespace,
) -> Tuple[int, int, int, List[Dict[str, Any]]]:
    """追溯冲突链：从 DB 查出所有冲突关联文档，逐条审计，一次性解决后继续。

    返回 (applied, merged, discovered, chain_results)。
    """
    applied = 0
    merged = 0
    discovered = 0
    chain: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = [
        (doc, repair_update, result)
    ]
    visited: set = {str(doc.get("_id"))}

    # 1. 追溯冲突链
    target_gid = _text(repair_update.get("$set", {}).get("global_role_id"))
    while target_gid:
        conflict_doc = await db[collection].find_one({
            "global_role_id": target_gid,
            "_id": {"$nin": list(visited)},
        })
        if not conflict_doc:
            break
        visited.add(str(conflict_doc.get("_id")))

        already_audited = bool(
            (conflict_doc.get("person_history_audit") or {}).get("audited_at")
        )
        if already_audited:
            _log("[CHAIN_TRACE] 关联文档已审计: identity_key={} global_role_id={}".format(
                _text(conflict_doc.get("identity_key")),
                _text(conflict_doc.get("global_role_id")),
            ))
            chain.append((conflict_doc, {}, {
                "collection": collection,
                "identity_key": _text(conflict_doc.get("identity_key")),
                "category": "confirmed_valid",
                "reason": "already_audited_chain_member",
            }))
            break

        _log("[CHAIN_TRACE] 追溯冲突链: 审计关联文档 identity_key={} global_role_id={}".format(
            _text(conflict_doc.get("identity_key")),
            _text(conflict_doc.get("global_role_id")),
        ))

        # 审计冲突文档（复用主循环相同逻辑）
        c_person_id = _text(conflict_doc.get("person_id"))
        c_expected = _expected_fields(conflict_doc)
        try:
            c_payload = await _fetch_payload(
                person_history_client, c_person_id, expected=c_expected,
            )
            c_api_error = not isinstance(c_payload, dict) or bool(c_payload.get("error"))
            if not c_api_error and c_person_id:
                discovered += await discover_new_roles_from_person_history(
                    db, c_payload, c_person_id,
                )
        except Exception as exc:
            c_payload = {"error": str(exc)}
            c_api_error = True

        c_correct = find_expected_role_candidate(
            c_payload if isinstance(c_payload, dict) else {}, c_expected,
        )
        c_repair = build_correct_global_repair_update(conflict_doc, collection, c_correct)
        c_repair_key = _text(c_repair.get("$set", {}).get("identity_key"))
        c_target_key_exists = False
        if c_repair_key:
            c_conflict = await db[collection].find_one({
                "$or": [
                    {"identity_key": c_repair_key},
                    {"global_role_id": _text(c_repair.get("$set", {}).get("global_role_id"))},
                ],
                "_id": {"$ne": conflict_doc.get("_id")},
            })
            c_target_key_exists = c_conflict is not None

        c_result = classify_identity_doc(
            conflict_doc,
            c_payload if isinstance(c_payload, dict) else {},
            collection,
            target_key_exists=c_target_key_exists,
            api_error=c_api_error,
        )
        if c_result["category"] in ("confirmed_dirty", "conflict_needs_manual_merge"):
            c_result["repair_update"] = c_repair if c_repair else None
        chain.append((conflict_doc, c_repair, c_result))

        if (
            c_result["category"] in ("confirmed_dirty", "conflict_needs_manual_merge")
            and c_repair
        ):
            target_gid = _text(c_repair.get("$set", {}).get("global_role_id"))
        else:
            break

    _log("[CHAIN_TRACE] 冲突链完整: {} 条文档".format(len(chain)))

    # 2. 尝试策略：同角色重复合并
    if len(chain) >= 2:
        chain_items = [
            (collection, d, u, r, 0, 0) for d, u, r in chain if u
        ]
        if chain_items:
            duplicate_groups = detect_same_role_duplicates(chain_items)
            for grp_collection, group in duplicate_groups:
                g_merged, g_details = await resolve_duplicate_merge(
                    db, grp_collection, group, match_history_client,
                )
                merged += g_merged
                if g_merged:
                    archived_keys = {d["archived_identity_key"] for d in g_details}
                    chain[:] = [
                        (d, u, r) for d, u, r in chain
                        if _text(d.get("identity_key")) not in archived_keys
                    ]
                    for detail in g_details:
                        _log("[CHAIN_MERGE] 冲突链合并归档: {} -> {}".format(
                            detail["archived_identity_key"], detail["replaced_by"],
                        ))

    # 3. 尝试策略：从叶子到根链式修复
    for chain_doc, chain_repair, chain_result in reversed(chain):
        if chain_result["category"] not in ("confirmed_dirty", "conflict_needs_manual_merge"):
            continue
        if not chain_repair:
            continue
        target_gid = _text(chain_repair.get("$set", {}).get("global_role_id"))
        exists = await db[collection].find_one({
            "global_role_id": target_gid,
            "_id": {"$ne": chain_doc.get("_id")},
        })
        if not exists:
            try:
                await db[collection].update_one(
                    {"_id": chain_doc.get("_id")}, chain_repair,
                )
                applied += 1
                chain_result["category"] = "confirmed_dirty"
                chain_result["reason"] = "chain_resolved_inline"
                _log("[CHAIN_FIX] 链式修复: {} -> {}".format(
                    _text(chain_doc.get("identity_key")),
                    _text(chain_repair.get("$set", {}).get("identity_key")),
                ))
            except Exception as exc:
                _log("[CHAIN_FAIL] 链式修复失败: {} ({})".format(
                    _text(chain_doc.get("identity_key")), exc,
                ))

    # 4. 标记链上所有文档已审计（已通过 repair_update 写过的也不会重复写）
    if args.apply:
        for chain_doc, chain_repair, chain_result in chain:
            if not chain_repair or chain_result["category"] not in (
                "confirmed_dirty", "conflict_needs_manual_merge",
            ):
                await _mark_audited(db, collection, chain_doc.get("_id"))

    chain_results = [r for _, _, r in chain]
    return applied, merged, discovered, chain_results


async def run_audit(
    db: Any,
    person_history_client: Any,
    match_history_client: Any,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    normalize_repair_flags(args)
    ensure_apply_allowed(bool(args.apply), bool(args.yes))
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = ROOT / "data" / "jjc_identity_audit" / timestamp
    details_dir = report_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    details: Dict[str, List[Dict[str, Any]]] = {category: [] for category in REPORT_CATEGORIES}
    query = _base_filter(args)
    applied = 0
    discovered = 0
    merged = 0
    all_items: List[Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any], int, int]] = []

    for collection in _collection_names(args.collection):
        total_count = await db[collection].count_documents(query)
        process_count = min(total_count, int(args.limit)) if args.limit else total_count
        _log("[{}] 待审计数据: total={} process={} filter={}".format(
            collection,
            total_count,
            process_count,
            json.dumps(query, ensure_ascii=False, default=str),
        ))
        cursor = db[collection].find(query)
        if args.limit:
            cursor = cursor.limit(int(args.limit))
        docs = await cursor.to_list(length=args.limit or None)
        for index, doc in enumerate(docs, start=1):
            person_id = _text(doc.get("person_id"))
            expected = _expected_fields(doc)
            _log("[{}] ({}/{}) 开始审计: {}".format(
                collection,
                index,
                process_count,
                _format_expected(expected),
            ))
            try:
                _log("[{}] ({}/{}) 开始查找 person-history: person_id={}".format(
                    collection,
                    index,
                    process_count,
                    person_id or "-",
                ))
                await random_sleep()
                payload = await _fetch_payload(
                    person_history_client,
                    person_id,
                    expected=expected,
                )
                api_error = not isinstance(payload, dict) or bool(payload.get("error"))
                if api_error:
                    _log("[{}] ({}/{}) person-history 查询失败: {}".format(
                        collection,
                        index,
                        process_count,
                        _text(payload.get("error") if isinstance(payload, dict) else ""),
                    ))
                else:
                    _log("[{}] ({}/{}) person-history 已读取候选数: {}".format(
                        collection,
                        index,
                        process_count,
                        len(extract_history_items(payload)),
                    ))
                    if person_id:
                        discovered += await discover_new_roles_from_person_history(
                            db, payload, person_id,
                        )
            except Exception as exc:
                payload = {"error": str(exc)}
                api_error = True
                _log("[{}] ({}/{}) person-history 查询异常: {}".format(
                    collection,
                    index,
                    process_count,
                    exc,
                ))

            correct_candidate = find_expected_role_candidate(
                payload if isinstance(payload, dict) else {},
                expected,
            )
            if correct_candidate:
                _log("[{}] ({}/{}) 查找到匹配角色: global_role_id={} server={} role_name={}".format(
                    collection,
                    index,
                    process_count,
                    correct_candidate.get("global_role_id") or "-",
                    correct_candidate.get("server") or "-",
                    correct_candidate.get("role_name") or "-",
                ))
            else:
                _log("[{}] ({}/{}) 未查找到匹配角色".format(collection, index, process_count))
            repair_update = build_correct_global_repair_update(doc, collection, correct_candidate)
            repair_key = _text(repair_update.get("$set", {}).get("identity_key"))
            repaired_global_role_id = _text(repair_update.get("$set", {}).get("global_role_id"))
            target_key_exists = False
            if repair_key:
                conflict = await db[collection].find_one({
                    "$or": [
                        {"identity_key": repair_key},
                        {"global_role_id": repaired_global_role_id},
                    ],
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
            if result["category"] == "confirmed_valid":
                _log("[{}] ({}/{}) 匹配: category={} reason={}".format(
                    collection,
                    index,
                    process_count,
                    result["category"],
                    result.get("reason", ""),
                ))
            else:
                _log("[{}] ({}/{}) 不匹配/需关注: category={} reason={}".format(
                    collection,
                    index,
                    process_count,
                    result["category"],
                    result.get("reason", ""),
                ))
            if result["category"] == "confirmed_dirty":
                result["repair_update"] = repair_update if repair_update else None
                if not repair_update:
                    _log("[{}] ({}/{}) 跳过修改: 未找到可写入的正确 global_role_id".format(
                        collection,
                        index,
                        process_count,
                    ))
            elif result["category"] == "conflict_needs_manual_merge":
                result["repair_update"] = repair_update if repair_update else None
                _log("[NEEDS_MANUAL] collection={} identity_key={} person_id={} old_global_role_id={} new_global_role_id={} repair_key={} server={} role_name={}".format(
                    collection,
                    _text(doc.get("identity_key")),
                    _text(doc.get("person_id")),
                    _text(doc.get("global_role_id")),
                    _text(repair_update.get("$set", {}).get("global_role_id") if repair_update else ""),
                    repair_key or "-",
                    _text(doc.get("server") or doc.get("name")),
                    _text(doc.get("role_name") or doc.get("name")),
                ))
            all_items.append((collection, doc, repair_update, result, index, process_count))
            details[result["category"]].append(result)

            # 逐条立即修复 / 标记已审计
            if args.apply:
                if result["category"] == "confirmed_dirty" and repair_update:
                    try:
                        await db[collection].update_one({"_id": doc.get("_id")}, repair_update)
                        applied += 1
                        _log("[{}] ({}/{}) 立即修复完成: {} -> {}".format(
                            collection, index, process_count,
                            _text(doc.get("identity_key")),
                            _text(repair_update.get("$set", {}).get("identity_key")),
                        ))
                    except Exception as exc:
                        _log("[{}] ({}/{}) 立即修复Mongo错误: {} -> 追溯冲突链解决".format(
                            collection, index, process_count, exc,
                        ))
                        details["confirmed_dirty"][:] = [
                            d for d in details["confirmed_dirty"]
                            if d.get("identity_key") != result.get("identity_key")
                            or d.get("collection") != result.get("collection")
                        ]
                        result["category"] = "conflict_needs_manual_merge"
                        result["reason"] = "immediate_repair_duplicate_key"
                        details["conflict_needs_manual_merge"].append(result)
                        chain_applied, chain_merged, chain_discovered, chain_results = \
                            await _resolve_conflict_chain(
                                db, person_history_client, match_history_client,
                                collection, doc, repair_update, result, args,
                            )
                        applied += chain_applied
                        merged += chain_merged
                        discovered += chain_discovered
                        for cr in chain_results:
                            if cr.get("identity_key") != result.get("identity_key") or cr.get("collection") != result.get("collection"):
                                details[cr["category"]].append(cr)
                            elif cr.get("reason") != result.get("reason"):
                                details[result["category"]][:] = [
                                    d for d in details[result["category"]]
                                    if d.get("identity_key") != result.get("identity_key")
                                    or d.get("collection") != result.get("collection")
                                ]
                                result.update(cr)
                                details[cr["category"]].append(result)
                elif result["category"] == "conflict_needs_manual_merge" and repair_update:
                    # 当场追溯冲突链，一次性解决
                    chain_applied, chain_merged, chain_discovered, chain_results = \
                        await _resolve_conflict_chain(
                            db, person_history_client, match_history_client,
                            collection, doc, repair_update, result, args,
                        )
                    applied += chain_applied
                    merged += chain_merged
                    discovered += chain_discovered
                    # 将链上各文档的审计结果并入 details（当前 doc 已在 details 中）
                    for cr in chain_results:
                        if cr.get("identity_key") != result.get("identity_key") or cr.get("collection") != result.get("collection"):
                            details[cr["category"]].append(cr)
                        elif cr.get("reason") != result.get("reason"):
                            # 同一文档分类变化，更新 details
                            details[result["category"]][:] = [
                                d for d in details[result["category"]]
                                if d.get("identity_key") != result.get("identity_key")
                                or d.get("collection") != result.get("collection")
                            ]
                            result.update(cr)
                            details[cr["category"]].append(result)
                elif result["category"] == "confirmed_dirty" and not repair_update:
                    await _mark_audited(db, collection, doc.get("_id"))
                elif result["category"] not in ("confirmed_dirty", "conflict_needs_manual_merge"):
                    await _mark_audited(db, collection, doc.get("_id"))

    # Dry-run log for confirmed_dirty items that weren't applied
    if not args.apply:
        for collection, doc, repair_update, result, index, process_count in all_items:
            if result["category"] == "confirmed_dirty" and repair_update:
                _log("[{}] ({}/{}) dry-run: 将修复为 {}".format(
                    collection,
                    index,
                    process_count,
                    _text(repair_update.get("$set", {}).get("identity_key")) or "-",
                ))
        duplicate_groups = detect_same_role_duplicates(all_items)
        if duplicate_groups:
            _log("========== 同角色重复文档 (dry-run): {} 组 ==========".format(len(duplicate_groups)))
            for collection, group in duplicate_groups:
                gids = [_text(d[1].get("global_role_id")) for d in group]
                _log("[MERGE_DRY_RUN] collection={} server={} name={} gids={}".format(
                    collection,
                    _text(group[0][1].get("server") or group[0][1].get("name")),
                    _text(group[0][1].get("role_name") or group[0][1].get("name")),
                    gids,
                ))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": not bool(args.apply),
        "applied": applied,
        "discovered": discovered,
        "merged": merged,
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
    normalize_repair_flags(args)
    ensure_apply_allowed(bool(args.apply), bool(args.yes))
    from motor.motor_asyncio import AsyncIOMotorClient

    import config as cfg
    from src.services.jx3.match_history import PersonMatchHistoryClient, MatchHistoryClient
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
    match_history_client = MatchHistoryClient(
        match_history_url=cfg.API_URLS["竞技场战局历史"],
        tuilan_request=tuilan_request,
    )
    summary = await run_audit(db, person_history_client, match_history_client, args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="审计 JJC person-history 身份错绑")
    parser.add_argument("--collection", choices=("role_identities", "jjc_sync_role_queue", "all"), default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--server", default="", help="按问题角色区服筛选")
    parser.add_argument("--name", default="", help="按问题角色名筛选")
    parser.add_argument("--person-id", default="")
    parser.add_argument("--global-role-id", default="")
    parser.add_argument("--apply", action="store_true", help="执行明确脏数据修复")
    parser.add_argument("--yes", action="store_true", help="与 --apply 配合确认写库")
    parser.add_argument("--repair", action="store_true", help="便捷修复模式，等价于 --apply --yes")
    parser.add_argument("--reprocess", action="store_true", help="忽略已审计标记，强制重审全部文档")
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
