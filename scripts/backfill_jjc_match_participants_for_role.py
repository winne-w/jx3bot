#!/usr/bin/env python3
"""Backfill jjc_match_participants for one role from cached match_detail docs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase  # noqa: E402

from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo  # noqa: E402


def _log(message: str) -> None:
    print(message, flush=True)


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _pick_str(*values: Any) -> Optional[str]:
    return JjcMatchParticipantRepo._pick_str(*values)


def _coerce_int(value: Any) -> Optional[int]:
    return JjcMatchParticipantRepo._coerce_int(value)


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


def get_db(client: AsyncIOMotorClient, db_name: Optional[str]) -> AsyncIOMotorDatabase:
    if db_name:
        return client[db_name]
    default_db = client.get_default_database(default=None)
    if default_db is not None:
        return default_db
    return client["jx3bot"]


def role_display_names(server: str, name: str) -> List[str]:
    names = [name, "{}·{}".format(name, server)]
    result: List[str] = []
    seen: Set[str] = set()
    for item in names:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def build_detail_role_query(server: str, name: str, global_ids: Set[str]) -> Dict[str, Any]:
    names = role_display_names(server, name)
    player_name_match = {
        "server": server,
        "role_name": {"$in": names},
    }
    or_terms: List[Dict[str, Any]] = [
        {"data.detail.team1.players_info": {"$elemMatch": player_name_match}},
        {"data.detail.team2.players_info": {"$elemMatch": player_name_match}},
    ]
    if global_ids:
        sorted_global_ids = sorted(global_ids)
        or_terms.extend([
            {"data.detail.team1.players_info.global_id": {"$in": sorted_global_ids}},
            {"data.detail.team2.players_info.global_id": {"$in": sorted_global_ids}},
        ])
    return {
        "data.unavailable": {"$ne": True},
        "$or": or_terms,
    }


def iter_detail_players(detail: Dict[str, Any]) -> List[Tuple[str, int, Dict[str, Any]]]:
    result: List[Tuple[str, int, Dict[str, Any]]] = []
    for team_key in ("team1", "team2"):
        team = detail.get(team_key)
        if not isinstance(team, dict):
            continue
        players = team.get("players_info") or []
        if not isinstance(players, list):
            continue
        for index, player in enumerate(players):
            if isinstance(player, dict):
                result.append((team_key, index, player))
    return result


def is_target_player(player: Dict[str, Any], *, server: str, name: str, global_ids: Set[str]) -> bool:
    global_id = _pick_str(player.get("global_id"), player.get("globalId"))
    if global_id and global_id in global_ids:
        return True
    player_server = _pick_str(player.get("server"), player.get("server_name"), player.get("serverName"))
    role_name = _pick_str(player.get("role_name"), player.get("roleName"), player.get("name"))
    return _normalize(player_server) == _normalize(server) and role_name in set(role_display_names(server, name))


async def load_role_global_ids(db: AsyncIOMotorDatabase, server: str, name: str) -> Set[str]:
    cursor = db.role_identities.find(
        {
            "normalized_server": _normalize(server),
            "normalized_name": _normalize(name),
        },
        {"global_id": 1},
    )
    docs = await cursor.to_list(length=None)
    global_ids: Set[str] = set()
    for doc in docs:
        global_id = _pick_str(doc.get("global_id"))
        if global_id:
            global_ids.add(global_id)
    return global_ids


async def load_seen_docs(db: AsyncIOMotorDatabase, match_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not match_ids:
        return {}
    cursor = db.jjc_sync_match_seen.find({"match_id": {"$in": match_ids}})
    docs = await cursor.to_list(length=None)
    result: Dict[int, Dict[str, Any]] = {}
    for doc in docs:
        match_id = _coerce_int(doc.get("match_id"))
        if match_id is not None:
            result[match_id] = doc
    return result


async def find_missing_matches(
    db: AsyncIOMotorDatabase,
    *,
    server: str,
    name: str,
    global_ids: Set[str],
) -> Dict[str, Any]:
    query = build_detail_role_query(server, name, global_ids)
    projection = {
        "match_id": 1,
        "cached_at": 1,
        "data.detail": 1,
        "data.unavailable": 1,
        "data.match_id": 1,
        "data.match_time": 1,
        "data.start_time": 1,
    }
    cursor = db.jjc_match_detail.find(query, projection).sort("match_id", 1)
    detail_docs = await cursor.to_list(length=None)

    target_rows: List[Dict[str, Any]] = []
    projectable_match_ids: Set[int] = set()
    missing_without_global_id: List[int] = []
    existing_rows = 0

    for doc in detail_docs:
        match_id = _coerce_int(doc.get("match_id"))
        if match_id is None:
            continue
        data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
        detail = data.get("detail") if isinstance(data.get("detail"), dict) else {}
        if not isinstance(detail, dict):
            continue
        for team_key, player_index, player in iter_detail_players(detail):
            if not is_target_player(player, server=server, name=name, global_ids=global_ids):
                continue
            global_id = _pick_str(player.get("global_id"), player.get("globalId"))
            target_rows.append({
                "match_id": match_id,
                "global_id": global_id,
                "team_key": team_key,
                "player_index": player_index,
                "role_name": _pick_str(player.get("role_name"), player.get("roleName"), player.get("name")),
                "server": _pick_str(player.get("server"), player.get("server_name"), player.get("serverName")),
            })
            if not global_id:
                missing_without_global_id.append(match_id)
                continue
            projectable_match_ids.add(match_id)
            existing = await db.jjc_match_participants.find_one(
                {
                    "match_id": match_id,
                    "global_id": global_id,
                    "match_type": 3,
                    "detail_available": True,
                },
                {"_id": 1},
            )
            if existing is None:
                pass
            else:
                existing_rows += 1

    docs_by_match_id: Dict[int, Dict[str, Any]] = {}
    for doc in detail_docs:
        match_id = _coerce_int(doc.get("match_id"))
        if match_id is not None:
            docs_by_match_id[match_id] = doc

    return {
        "detail_docs": detail_docs,
        "docs_by_match_id": docs_by_match_id,
        "target_rows": target_rows,
        "projectable_match_ids": sorted(projectable_match_ids),
        "missing_without_global_id": sorted(set(missing_without_global_id)),
        "existing_rows": existing_rows,
    }


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    client = AsyncIOMotorClient(args.mongo_uri or get_mongo_uri(), serverSelectionTimeoutMS=8000)
    try:
        db = get_db(client, args.db_name)
        await db.command("ping")
        repo = JjcMatchParticipantRepo(db=db)

        global_ids = await load_role_global_ids(db, args.server, args.name)
        found = await find_missing_matches(
            db,
            server=args.server,
            name=args.name,
            global_ids=global_ids,
        )
        projectable_match_ids: List[int] = found["projectable_match_ids"]
        seen_by_match_id = await load_seen_docs(db, projectable_match_ids)
        selected_match_ids: List[int] = []
        built_by_match_id: Dict[int, List[Dict[str, Any]]] = {}
        rebuild_reasons: List[Dict[str, Any]] = []
        not_3v3_or_unbuildable: List[int] = []

        for match_id in projectable_match_ids:
            doc = found["docs_by_match_id"].get(match_id)
            if not doc:
                continue
            payload = {"cached_at": doc.get("cached_at"), "data": doc.get("data")}
            try:
                participants = repo.build_participants_from_match_detail(
                    match_id,
                    payload,
                    seen_doc=seen_by_match_id.get(match_id),
                    detail_source=JjcMatchParticipantRepo.DETAIL_SOURCE_MANUAL,
                )
            except Exception as exc:
                rebuild_reasons.append({"match_id": match_id, "reason": "build_failed", "error": str(exc)})
                continue
            if not participants:
                not_3v3_or_unbuildable.append(match_id)
                continue
            expected_global_ids = {
                str(item.get("global_id"))
                for item in participants
                if item.get("global_id") is not None
            }
            cursor = db.jjc_match_participants.find(
                {
                    "match_id": match_id,
                    "match_type": 3,
                    "detail_available": True,
                },
                {"global_id": 1},
            )
            existing_docs = await cursor.to_list(length=None)
            existing_global_ids = {
                str(item.get("global_id"))
                for item in existing_docs
                if item.get("global_id") is not None
            }
            if expected_global_ids != existing_global_ids:
                selected_match_ids.append(match_id)
                built_by_match_id[match_id] = participants
                rebuild_reasons.append({
                    "match_id": match_id,
                    "reason": "match_projection_diff",
                    "expected_rows": len(expected_global_ids),
                    "existing_rows": len(existing_global_ids),
                    "missing_global_ids": sorted(expected_global_ids - existing_global_ids),
                    "extra_global_ids": sorted(existing_global_ids - expected_global_ids),
                })

        total_mismatched_matches = len(selected_match_ids)
        if args.limit:
            selected_match_ids = selected_match_ids[: max(0, int(args.limit))]
        stats: Dict[str, Any] = {
            "mode": "apply" if args.apply else "dry_run",
            "server": args.server,
            "name": args.name,
            "global_ids": sorted(global_ids),
            "detail_target_rows": len(found["target_rows"]),
            "projectable_detail_matches": len(found["projectable_match_ids"]),
            "existing_target_projected_rows": found["existing_rows"],
            "mismatched_projectable_matches": total_mismatched_matches,
            "missing_without_global_id_matches": len(found["missing_without_global_id"]),
            "selected_rebuild_matches": len(selected_match_ids),
            "written_matches": 0,
            "participant_rows_built": 0,
            "not_3v3_or_unbuildable": not_3v3_or_unbuildable,
            "failed": [],
            "rebuild_reasons_sample": rebuild_reasons[:50],
            "missing_without_global_id_sample": found["missing_without_global_id"][:50],
        }

        for match_id in selected_match_ids:
            doc = found["docs_by_match_id"].get(match_id)
            if not doc:
                stats["failed"].append({"match_id": match_id, "reason": "detail_doc_not_loaded"})
                continue
            participants = built_by_match_id.get(match_id)
            if not participants:
                stats["failed"].append({"match_id": match_id, "reason": "participants_not_built"})
                continue
            stats["participant_rows_built"] += len(participants)
            if args.apply:
                try:
                    await repo.replace_match_participants(match_id, participants)
                    stats["written_matches"] += 1
                except Exception as exc:
                    stats["failed"].append({"match_id": match_id, "reason": "write_failed", "error": str(exc)})

        return stats
    finally:
        client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按服务器和角色名补齐 JJC 对局参与者投影表")
    parser.add_argument("server", help="服务器名称，例如：唯满侠")
    parser.add_argument("name", help="角色名称，例如：桃桃白糖")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI；默认读取 runtime_config/config/env")
    parser.add_argument("--db-name", default=None, help="数据库名；默认从 MongoDB URI 解析")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个整场投影不一致的对局；0 表示不限制")
    parser.add_argument("--apply", action="store_true", help="执行写库；不传则只 dry-run")
    parser.add_argument("--yes", action="store_true", help="与 --apply 配合确认写库")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.apply and not args.yes:
        raise SystemExit("--apply requires --yes")
    stats = asyncio.run(run(args))
    _log(json.dumps(stats, ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if stats.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
