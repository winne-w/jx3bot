#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ROOT = Path("data/jjc_ranking_stats")


def _load_runtime_mongo_uri() -> str:
    uri = os.getenv("MONGO_URI")
    if uri:
        return uri

    runtime_config_path = Path("runtime_config.json")
    if runtime_config_path.is_file():
        try:
            payload = json.loads(runtime_config_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        uri = payload.get("MONGO_URI")
        if uri:
            return str(uri)

    raise RuntimeError("无法获取 MONGO_URI：环境变量 MONGO_URI 和 runtime_config.json 均未配置")


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _iter_timestamps(root: Path, requested: Optional[List[str]]) -> List[str]:
    if requested:
        return [item for item in requested if item.isdigit()]

    timestamps = set()
    if not root.is_dir():
        return []
    for path in root.iterdir():
        if path.is_dir() and path.name.isdigit() and (path / "summary.json").is_file():
            timestamps.add(path.name)
        if path.is_file() and path.suffix == ".json" and path.stem.isdigit():
            timestamps.add(path.stem)
    return sorted(timestamps)


def _iter_detail_files(timestamp: str) -> Iterable[Path]:
    details_root = ROOT / timestamp / "details"
    if not details_root.is_dir():
        return []
    return sorted(details_root.glob("*/*/*.json"))


def _member_lookup_keys(member: Dict[str, Any]) -> List[Dict[str, Any]]:
    queries: List[Dict[str, Any]] = []
    global_role_id = str(member.get("global_role_id") or "").strip()
    if global_role_id:
        queries.append({"global_role_id": global_role_id})

    zone = str(member.get("zone") or "").strip()
    game_role_id = str(member.get("game_role_id") or "").strip()
    if zone and game_role_id:
        queries.append({"zone": zone, "game_role_id": game_role_id})

    server = _normalize(member.get("server"))
    name = _normalize(member.get("name"))
    if server and name:
        queries.append({"normalized_server": server, "normalized_name": name})

    return queries


async def _load_weapon_name(
    db: AsyncIOMotorDatabase,
    member: Dict[str, Any],
    lookup_cache: Dict[Tuple[Tuple[str, str], ...], Optional[str]],
) -> Optional[str]:
    queries = _member_lookup_keys(member)
    cache_key = tuple(tuple(sorted(query.items())) for query in queries)
    if cache_key in lookup_cache:
        return lookup_cache[cache_key]

    for query in queries:
        doc = await db.role_jjc_cache.find_one(query, {"weapon.name": 1})
        if not doc:
            continue
        weapon = doc.get("weapon")
        if isinstance(weapon, dict):
            weapon_name = weapon.get("name")
            if weapon_name:
                lookup_cache[cache_key] = str(weapon_name)
                return lookup_cache[cache_key]

    server = str(member.get("server") or "").strip()
    name = str(member.get("name") or "").strip()
    if server and name:
        try:
            doc = await db.kungfu_cache.find_one(
                {"server": server, "name": name},
                {"weapon.name": 1},
                max_time_ms=1000,
            )
        except Exception:
            doc = None
        if doc:
            weapon = doc.get("weapon")
            if isinstance(weapon, dict):
                weapon_name = weapon.get("name")
                if weapon_name:
                    lookup_cache[cache_key] = str(weapon_name)
                    return lookup_cache[cache_key]
    lookup_cache[cache_key] = None
    return None


async def _hydrate_members(
    db: AsyncIOMotorDatabase,
    members: List[Any],
    lookup_cache: Dict[Tuple[Tuple[str, str], ...], Optional[str]],
) -> Tuple[int, int]:
    changed = 0
    missing = 0
    for member in members:
        if not isinstance(member, dict):
            continue
        if member.get("weapon_name"):
            continue
        weapon_name = await _load_weapon_name(db, member, lookup_cache)
        if weapon_name:
            member["weapon_name"] = weapon_name
            changed += 1
        else:
            missing += 1
    return changed, missing


def _iter_legacy_member_lists(payload: Dict[str, Any]) -> Iterable[Tuple[str, str, str, List[Any]]]:
    stats = payload.get("kungfu_statistics") or {}
    for range_key, range_stats in stats.items():
        if not isinstance(range_stats, dict):
            continue
        for lane_name in ("healer", "dps"):
            lane = range_stats.get(lane_name)
            if not isinstance(lane, dict):
                continue
            members_map = lane.get("members") or {}
            if not isinstance(members_map, dict):
                continue
            for kungfu, members in members_map.items():
                if isinstance(members, list):
                    yield str(range_key), lane_name, str(kungfu), members


def _is_legendary(member: Dict[str, Any], legendary_names: set) -> bool:
    if str(member.get("weapon_quality")) != "5":
        return False
    weapon_name = member.get("weapon_name")
    weapon = member.get("weapon")
    if not weapon_name and isinstance(weapon, dict):
        weapon_name = weapon.get("name")
    if not weapon_name:
        return False
    return str(weapon_name) in legendary_names


def _rebuild_summary_counts(timestamp: str, legendary_names: set) -> Tuple[bool, int]:
    summary_path = ROOT / timestamp / "summary.json"
    if not summary_path.is_file():
        return False, 0

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    changed_count = 0
    stats = summary.get("kungfu_statistics") or {}
    for range_key, range_stats in stats.items():
        if not isinstance(range_stats, dict):
            continue
        for lane_name in ("healer", "dps"):
            lane = range_stats.get(lane_name)
            if not isinstance(lane, dict):
                continue
            count_map = lane.get("legendary_count_map")
            if not isinstance(count_map, dict):
                count_map = {}
                lane["legendary_count_map"] = count_map

            for detail_path in sorted((ROOT / timestamp / "details" / range_key / lane_name).glob("*.json")):
                detail = json.loads(detail_path.read_text(encoding="utf-8"))
                kungfu = detail.get("kungfu")
                if not kungfu:
                    continue
                members = detail.get("members") or []
                new_count = sum(
                    1
                    for member in members
                    if isinstance(member, dict) and _is_legendary(member, legendary_names)
                )
                if count_map.get(kungfu) != new_count:
                    changed_count += 1
                    count_map[kungfu] = new_count

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, changed_count


async def _fix_timestamp(
    db: AsyncIOMotorDatabase,
    timestamp: str,
    *,
    write: bool,
    legendary_names: set,
) -> Dict[str, Any]:
    detail_files = list(_iter_detail_files(timestamp))
    result: Dict[str, Any] = {
        "timestamp": timestamp,
        "detail_files": len(detail_files),
        "legacy_file": (ROOT / "{}.json".format(timestamp)).is_file(),
        "members_changed": 0,
        "members_missing": 0,
        "summary_count_changes": 0,
        "would_write": write,
    }

    lookup_cache: Dict[Tuple[Tuple[str, str], ...], Optional[str]] = {}

    changed_payloads: List[Tuple[Path, Dict[str, Any]]] = []
    for detail_path in detail_files:
        payload = json.loads(detail_path.read_text(encoding="utf-8"))
        members = payload.get("members")
        if not isinstance(members, list):
            continue
        changed, missing = await _hydrate_members(db, members, lookup_cache)
        result["members_changed"] += changed
        result["members_missing"] += missing
        if changed:
            changed_payloads.append((detail_path, payload))

    legacy_path = ROOT / "{}.json".format(timestamp)
    legacy_payload: Optional[Dict[str, Any]] = None
    legacy_changed = False
    if legacy_path.is_file():
        legacy_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        if isinstance(legacy_payload, dict):
            for _, _, _, members in _iter_legacy_member_lists(legacy_payload):
                changed, missing = await _hydrate_members(db, members, lookup_cache)
                result["members_changed"] += changed
                result["members_missing"] += missing
                if changed:
                    legacy_changed = True

    if write:
        for detail_path, payload in changed_payloads:
            detail_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _, summary_changes = _rebuild_summary_counts(timestamp, legendary_names)
        result["summary_count_changes"] = summary_changes
        if legacy_changed and legacy_payload is not None:
            legacy_path.write_text(json.dumps(legacy_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        temp_changes = 0
        for _, payload in changed_payloads:
            members = payload.get("members") or []
            old_count = sum(
                1 for member in members if isinstance(member, dict) and str(member.get("weapon_quality")) == "5"
            )
            new_count = sum(
                1 for member in members if isinstance(member, dict) and _is_legendary(member, legendary_names)
            )
            if old_count != new_count:
                temp_changes += 1
        result["summary_count_changes"] = temp_changes

    return result


async def _main_async(args: argparse.Namespace) -> int:
    try:
        uri = _load_runtime_mongo_uri()
    except RuntimeError as exc:
        print("ERROR {}".format(exc), flush=True)
        return 1

    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    client: AsyncIOMotorClient = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
    except Exception as exc:
        print("ERROR MongoDB 连接失败: {}".format(exc), flush=True)
        return 1

    db = client[db_name]
    from config import JJC_LEGENDARY_WEAPON_NAMES

    timestamps = _iter_timestamps(ROOT, args.timestamp)
    if not timestamps:
        print("no split snapshots found", flush=True)
        client.close()
        return 0

    mode = "WRITE" if args.write else "DRY-RUN"
    print("mode={} timestamps={}".format(mode, ",".join(timestamps)), flush=True)
    for timestamp in timestamps:
        result = await _fix_timestamp(
            db,
            timestamp,
            write=args.write,
            legendary_names=set(JJC_LEGENDARY_WEAPON_NAMES),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)

    client.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="补齐 JJC 排名历史快照 weapon_name 并重算橙武计数")
    parser.add_argument("--timestamp", action="append", help="指定一个或多个拆分快照 timestamp")
    parser.add_argument("--write", action="store_true", help="实际写入 details 和 summary；默认 dry-run")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
