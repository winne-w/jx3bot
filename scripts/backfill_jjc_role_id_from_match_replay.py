#!/usr/bin/env python3
"""Backfill JJC role_id/global_id from Tuilan match replay data."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from src.services.jx3.jjc_match_data_sync import normalize_role_name  # noqa: E402
from src.services.jx3.role_identity_matching import build_identity_key, legacy_identity_keys  # noqa: E402
from src.utils.tuilan_request import tuilan_request  # noqa: E402

MATCH_REPLAY_URL = "https://m.pvp.xoyo.com/3c/mine/match/replay"
INDICATOR_URL = "https://m.pvp.xoyo.com/role/indicator"
COLLECTIONS = ("role_identities", "jjc_sync_role_queue")
SOURCE_REPLAY = "match_replay_backfill"
SOURCE_INDICATOR = "match_replay_indicator_backfill"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _text(value).lower()


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


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


def parse_replay_role_name(raw_name: Any) -> Optional[Dict[str, str]]:
    """Parse replay role_name like '角色名·服务器' into identity fields."""
    value = _text(raw_name)
    if not value or "·" not in value:
        return None
    name, server = value.rsplit("·", 1)
    name = _text(name)
    server = _text(server)
    if not name or not server:
        return None
    normalized_name = normalize_role_name(name, server)
    return {
        "server": server,
        "name": normalized_name,
        "normalized_server": _norm(server),
        "normalized_name": _norm(normalized_name),
    }


def extract_replay_players(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    data = payload.get("data") if isinstance(payload, dict) else None
    players = data.get("players") if isinstance(data, dict) else None
    if not isinstance(players, list):
        return [], 0

    parsed: List[Dict[str, Any]] = []
    skipped = 0
    for player in players:
        if not isinstance(player, dict):
            skipped += 1
            continue
        role_id = _text(player.get("role_id"))
        global_id = _text(player.get("global_role_id"))
        parsed_name = parse_replay_role_name(player.get("role_name"))
        if not role_id or not global_id or parsed_name is None:
            skipped += 1
            continue
        parsed.append({
            "role_id": role_id,
            "global_id": global_id,
            "raw_role_name": _text(player.get("role_name")),
            "kungfu_name": _text(player.get("kungfu_name")),
            "team": _text(player.get("team")),
            **parsed_name,
        })
    return parsed, skipped


def unique_players(players: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for player in players:
        key = (player["normalized_server"], player["normalized_name"])
        by_key.setdefault(key, []).append(player)

    result: List[Dict[str, Any]] = []
    conflicts = 0
    for items in by_key.values():
        role_ids = {_text(item.get("role_id")) for item in items}
        global_ids = {_text(item.get("global_id")) for item in items}
        if len(items) != 1 and (len(role_ids) != 1 or len(global_ids) != 1):
            conflicts += len(items)
            continue
        result.append(items[0])
    return result, conflicts


def is_missing_role_id(collection: str, doc: Dict[str, Any]) -> bool:
    if collection == "role_identities":
        return not _text(doc.get("role_id") or doc.get("game_role_id"))
    return not _text(doc.get("role_id"))


def build_update(
    collection: str,
    doc: Dict[str, Any],
    player: Dict[str, Any],
    match_time: Optional[int],
    source: str,
    now: float,
    global_role_id: Optional[str] = None,
    person_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    role_id = _text(player.get("role_id"))
    if not role_id:
        return None, "missing_replay_role_id"

    existing_role_id = _text(doc.get("role_id") or doc.get("game_role_id"))
    if existing_role_id and existing_role_id != role_id:
        return None, "role_id_conflict"

    global_id = _text(player.get("global_id"))
    existing_global_id = _text(doc.get("global_id"))
    if global_id and existing_global_id and existing_global_id != global_id:
        return None, "global_id_conflict"

    existing_global_role_id = _text(doc.get("global_role_id"))
    if global_role_id and existing_global_role_id and existing_global_role_id != global_role_id:
        return None, "global_role_id_conflict"

    missing_role_id = is_missing_role_id(collection, doc)
    missing_global_id = bool(global_id and not existing_global_id)
    missing_global_role_id = bool(global_role_id and not existing_global_role_id)
    missing_person = bool(person_id and not _text(doc.get("person_id")))
    has_missing = missing_role_id or missing_global_id or missing_global_role_id or missing_person
    observed = _coerce_int(doc.get("role_info_observed_match_time"))
    newer = match_time is not None and (observed is None or match_time > observed)
    if not has_missing and not newer:
        return None, "older_or_equal_complete"

    set_fields: Dict[str, Any] = {
        "role_id": role_id,
        "role_info_source": source,
        "role_info_updated_at": now,
        "updated_at": now,
    }
    if collection == "role_identities":
        set_fields["game_role_id"] = role_id
    if global_id:
        set_fields["global_id"] = global_id
    if global_role_id:
        set_fields["global_role_id"] = global_role_id
    if person_id:
        set_fields["person_id"] = person_id
    if match_time is not None:
        set_fields["role_info_observed_match_time"] = match_time

    update_op: Dict[str, Any] = {"$set": set_fields}
    if global_id:
        old_key = _text(doc.get("identity_key"))
        new_key, new_level = build_identity_key(
            global_id=global_id,
            global_role_id=global_role_id or existing_global_role_id,
            zone=_text(doc.get("zone")),
            game_role_id=role_id,
            server=_text(doc.get("normalized_server") or doc.get("server")),
            name=_text(doc.get("normalized_name") or doc.get("name")),
        )
        if old_key and old_key != new_key:
            set_fields["identity_key"] = new_key
            if collection == "role_identities":
                set_fields["identity_level"] = new_level
            aliases = legacy_identity_keys(
                global_role_id=global_role_id or existing_global_role_id,
                zone=_text(doc.get("zone")),
                game_role_id=role_id,
                server=_text(doc.get("normalized_server") or doc.get("server")),
                name=_text(doc.get("normalized_name") or doc.get("name")),
            )
            aliases.append(old_key)
            update_op["$addToSet"] = {"aliases": {"$each": sorted(set(aliases))}}

    return update_op, "update"


def find_target_docs(db: Any, player: Dict[str, Any], collections: Iterable[str]) -> List[Tuple[str, Dict[str, Any]]]:
    query = {
        "normalized_server": player["normalized_server"],
        "normalized_name": player["normalized_name"],
    }
    found: List[Tuple[str, Dict[str, Any]]] = []
    for collection in collections:
        for doc in db[collection].find(query):
            found.append((collection, doc))
    return found


def fetch_replay(match_id: int) -> Dict[str, Any]:
    payload = tuilan_request(MATCH_REPLAY_URL, {"match_id": int(match_id)})
    if not isinstance(payload, dict):
        return {"error": "invalid_replay_response"}
    return payload


def fetch_indicator(role_id: str, zone: str, server: str) -> Optional[Dict[str, str]]:
    payload = tuilan_request(INDICATOR_URL, {"role_id": role_id, "zone": zone, "server": server})
    if not isinstance(payload, dict):
        return None
    if payload.get("code") != 0:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    role_info = data.get("role_info")
    if not isinstance(role_info, dict):
        return None
    global_role_id = _text(role_info.get("global_role_id"))
    if not global_role_id.startswith("SK01-"):
        return None
    person_info = data.get("person_info")
    person_id = _text(person_info.get("person_id")) if isinstance(person_info, dict) else ""
    return {"global_role_id": global_role_id, "person_id": person_id}


def iter_matches(db: Any, args: argparse.Namespace) -> Iterable[Dict[str, Any]]:
    query: Dict[str, Any] = {"match_id": {"$exists": True}}
    if args.status:
        query["status"] = args.status
    if args.match_id:
        query["match_id"] = int(args.match_id)

    cursor = db.jjc_sync_match_seen.find(
        query,
        {"match_id": 1, "match_time": 1, "status": 1},
    ).sort("match_time", -1)
    if args.skip:
        cursor = cursor.skip(int(args.skip))
    if args.limit:
        cursor = cursor.limit(int(args.limit))
    return cursor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从推栏 match/replay 回填 JJC 角色 role_id/global_id")
    parser.add_argument("--limit", type=int, default=20, help="最多处理多少场对局，默认 20")
    parser.add_argument("--skip", type=int, default=0, help="跳过多少场")
    parser.add_argument("--match-id", type=int, default=None, help="只处理指定 match_id")
    parser.add_argument("--status", default="detail_saved", help="jjc_sync_match_seen 状态过滤，默认 detail_saved；传空字符串不过滤")
    parser.add_argument("--collections", default="all", choices=["all", "role_identities", "jjc_sync_role_queue"], help="更新目标集合")
    parser.add_argument("--sleep", type=float, default=None, help="每场对局后的固定 sleep 秒数；传入后覆盖 --sleep-min/--sleep-max")
    parser.add_argument("--sleep-min", type=float, default=1.0, help="每场对局后随机 sleep 下限秒数，默认 1.0")
    parser.add_argument("--sleep-max", type=float, default=3.0, help="每场对局后随机 sleep 上限秒数，默认 3.0")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写库；默认行为")
    parser.add_argument("--apply", action="store_true", help="执行写库")
    parser.add_argument("--yes", action="store_true", help="与 --apply 配合确认写库")
    return parser.parse_args()


def selected_collections(value: str) -> Tuple[str, ...]:
    if value == "all":
        return COLLECTIONS
    return (value,)


def main() -> int:
    args = parse_args()
    if args.apply and not args.yes:
        raise SystemExit("--apply requires --yes")
    if args.status == "":
        args.status = None
    if args.sleep_min < 0 or args.sleep_max < 0:
        raise SystemExit("--sleep-min/--sleep-max must be >= 0")
    if args.sleep_min > args.sleep_max:
        raise SystemExit("--sleep-min must be <= --sleep-max")

    client = MongoClient(get_mongo_uri(), serverSelectionTimeoutMS=8000)
    db = client.get_default_database()
    collections = selected_collections(args.collections)
    stats: Dict[str, int] = {
        "matches": 0,
        "replay_success": 0,
        "players": 0,
        "player_parse_skipped": 0,
        "player_conflicts": 0,
        "target_docs": 0,
        "updates": 0,
        "applied": 0,
        "skipped": 0,
        "role_id_conflicts": 0,
        "global_id_conflicts": 0,
        "global_role_id_conflicts": 0,
        "person_id_conflicts": 0,
        "replay_failed": 0,
        "indicator_success": 0,
        "indicator_failed": 0,
        "indicator_skipped": 0,
    }
    skip_reasons: Dict[str, int] = {}

    for match in iter_matches(db, args):
        match_id = _coerce_int(match.get("match_id"))
        if match_id is None:
            continue
        match_time = _coerce_int(match.get("match_time"))
        stats["matches"] += 1
        _log("[MATCH] match_id={} match_time={} status={}".format(
            match_id, match_time or "-", _text(match.get("status")) or "-",
        ))

        payload = fetch_replay(match_id)
        if payload.get("code") != 0:
            stats["replay_failed"] += 1
            _log("[REPLAY_FAIL] match_id={} code={} msg={} error={}".format(
                match_id, payload.get("code"), payload.get("msg"), payload.get("error"),
            ))
            continue
        stats["replay_success"] += 1
        players, parse_skipped = extract_replay_players(payload)
        players, player_conflicts = unique_players(players)
        stats["players"] += len(players)
        stats["player_parse_skipped"] += parse_skipped
        stats["player_conflicts"] += player_conflicts

        now = time.time()
        for player in players:
            targets = find_target_docs(db, player, collections)
            stats["target_docs"] += len(targets)
            if not targets:
                skip_reasons["target_not_found"] = skip_reasons.get("target_not_found", 0) + 1
                continue

            zone = ""
            for _, doc in targets:
                doc_zone = _text(doc.get("zone"))
                if doc_zone:
                    zone = doc_zone
                    break

            indicator_result = None
            source = SOURCE_REPLAY
            if zone:
                indicator_result = fetch_indicator(player["role_id"], zone, player["server"])
                if indicator_result is not None:
                    stats["indicator_success"] += 1
                    source = SOURCE_INDICATOR
                    _log("[INDICATOR_OK] role={}/{} zone={} global_id={} global_role_id={}".format(
                        player["server"], player["name"], zone, player["global_id"], indicator_result["global_role_id"],
                    ))
                else:
                    stats["indicator_failed"] += 1
                    skip_reasons["indicator_failed"] = skip_reasons.get("indicator_failed", 0) + 1
                    _log("[INDICATOR_FAIL] role={}/{} zone={}".format(
                        player["server"], player["name"], zone,
                    ))
            else:
                stats["indicator_skipped"] += 1
                skip_reasons["indicator_zone_missing"] = skip_reasons.get("indicator_zone_missing", 0) + 1

            global_role_id = indicator_result["global_role_id"] if indicator_result else None
            person_id = indicator_result["person_id"] if indicator_result else None
            if person_id is not None and not person_id:
                person_id = None

            for collection, doc in targets:
                doc_person_id = _text(doc.get("person_id"))
                write_person_id = person_id
                if person_id and doc_person_id and doc_person_id != person_id:
                    write_person_id = None
                    stats["person_id_conflicts"] += 1
                    skip_reasons["person_id_conflict"] = skip_reasons.get("person_id_conflict", 0) + 1
                    _log("[CONFLICT_PERSON] collection={} identity_key={} existing_person_id={} indicator_person_id={} role={}/{}".format(
                        collection,
                        _text(doc.get("identity_key")),
                        doc_person_id,
                        person_id,
                        player["server"],
                        player["name"],
                    ))
                update, reason = build_update(
                    collection,
                    doc,
                    player,
                    match_time,
                    source,
                    now,
                    global_role_id=global_role_id,
                    person_id=write_person_id,
                )
                if update is None:
                    stats["skipped"] += 1
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    if reason == "role_id_conflict":
                        stats["role_id_conflicts"] += 1
                        _log("[CONFLICT] collection={} identity_key={} existing_role_id={} replay_role_id={} role={}/{}".format(
                            collection,
                            _text(doc.get("identity_key")),
                            _text(doc.get("role_id") or doc.get("game_role_id")),
                            player["role_id"],
                            player["server"],
                            player["name"],
                        ))
                    elif reason == "global_id_conflict":
                        stats["global_id_conflicts"] += 1
                        _log("[CONFLICT_GLOBAL_ID] collection={} identity_key={} existing_global_id={} replay_global_id={} role={}/{}".format(
                            collection,
                            _text(doc.get("identity_key")),
                            _text(doc.get("global_id")),
                            player["global_id"],
                            player["server"],
                            player["name"],
                        ))
                    elif reason == "global_role_id_conflict":
                        stats["global_role_id_conflicts"] += 1
                        _log("[CONFLICT_GLOBAL] collection={} identity_key={} existing_global_role_id={} indicator_global_role_id={} role={}/{}".format(
                            collection,
                            _text(doc.get("identity_key")),
                            _text(doc.get("global_role_id")),
                            global_role_id,
                            player["server"],
                            player["name"],
                        ))
                    continue

                stats["updates"] += 1
                extra = ""
                if player.get("global_id"):
                    extra += " global_id={}".format(player["global_id"])
                if global_role_id:
                    extra += " global_role_id={}".format(global_role_id)
                if person_id:
                    extra += " person_id={}".format(person_id)
                _log("[UPDATE{}] collection={} identity_key={} role={}/{} role_id={} match_time={}{}".format(
                    "" if args.apply else "_DRY_RUN",
                    collection,
                    _text(doc.get("identity_key")),
                    player["server"],
                    player["name"],
                    player["role_id"],
                    match_time or "-",
                    extra,
                ))
                if args.apply:
                    result = db[collection].update_one({"_id": doc["_id"]}, update)
                    if result.matched_count:
                        stats["applied"] += 1

        sleep_seconds = (
            float(args.sleep)
            if args.sleep is not None
            else random.uniform(float(args.sleep_min), float(args.sleep_max))
        )
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    print(json.dumps({"stats": stats, "skip_reasons": skip_reasons}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
