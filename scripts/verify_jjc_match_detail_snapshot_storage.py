"""
验证 JJC 对局详情是否按快照拆表格式保存。

用法:
  python scripts/verify_jjc_match_detail_snapshot_storage.py
  python scripts/verify_jjc_match_detail_snapshot_storage.py --limit 5
  python scripts/verify_jjc_match_detail_snapshot_storage.py --match-id 123456
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

SOURCE_COLLECTION = "jjc_match_detail"
EQUIPMENT_COLLECTION = "jjc_equipment_snapshot"
TALENT_COLLECTION = "jjc_talent_snapshot"


def _get_mongo_uri() -> str:
    uri = os.getenv("MONGO_URI")
    if uri:
        return uri

    script_dir = Path(__file__).resolve().parent
    runtime_cfg_path = script_dir.parent / "runtime_config.json"
    if runtime_cfg_path.is_file():
        try:
            with open(str(runtime_cfg_path), "r", encoding="utf-8") as fh:
                runtime_cfg = json.load(fh)
            uri = runtime_cfg.get("MONGO_URI")
            if uri:
                return str(uri)
        except Exception:
            pass

    raise RuntimeError("无法获取 MONGO_URI：环境变量 MONGO_URI 和 runtime_config.json 均未配置")


def _iter_players(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    detail = data.get("detail")
    container = detail if isinstance(detail, dict) else data
    for team_key in ("team1", "team2"):
        team = container.get(team_key)
        if not isinstance(team, dict):
            continue
        players = team.get("players_info")
        if not isinstance(players, list):
            continue
        for player in players:
            if isinstance(player, dict):
                yield player


async def _load_docs(
    db: AsyncIOMotorDatabase,
    match_id: Optional[int],
    limit: int,
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if match_id is not None:
        query["match_id"] = match_id

    cursor = db[SOURCE_COLLECTION].find(query).sort("match_id", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def _verify_doc(db: AsyncIOMotorDatabase, doc: Dict[str, Any]) -> Tuple[int, int, int]:
    match_id = doc.get("match_id")
    data = doc.get("data")
    if not isinstance(data, dict):
        print("FAIL match_id={} data 不是 object".format(match_id), flush=True)
        return 0, 0, 1

    players_seen = 0
    ok_count = 0
    fail_count = 0

    for player in _iter_players(data):
        players_seen += 1
        role_name = player.get("role_name") or player.get("person_name") or ""
        has_inline_equipment = "armors" in player
        has_inline_talent = "talents" in player
        equipment_hash = player.get("equipment_snapshot_hash")
        talent_hash = player.get("talent_snapshot_hash")

        player_ok = True
        if has_inline_equipment or has_inline_talent:
            player_ok = False
            print(
                "FAIL match_id={} role={} 仍内联保存 armors/talents: armors={} talents={}".format(
                    match_id, role_name, has_inline_equipment, has_inline_talent,
                ),
                flush=True,
            )

        if not equipment_hash:
            player_ok = False
            print("FAIL match_id={} role={} 缺少 equipment_snapshot_hash".format(match_id, role_name), flush=True)
        else:
            snap = await db[EQUIPMENT_COLLECTION].find_one({"snapshot_hash": equipment_hash})
            if snap is None:
                player_ok = False
                print(
                    "FAIL match_id={} role={} 装备快照不存在 hash={}".format(
                        match_id, role_name, equipment_hash,
                    ),
                    flush=True,
                )

        if not talent_hash:
            player_ok = False
            print("FAIL match_id={} role={} 缺少 talent_snapshot_hash".format(match_id, role_name), flush=True)
        else:
            snap = await db[TALENT_COLLECTION].find_one({"snapshot_hash": talent_hash})
            if snap is None:
                player_ok = False
                print(
                    "FAIL match_id={} role={} 奇穴快照不存在 hash={}".format(
                        match_id, role_name, talent_hash,
                    ),
                    flush=True,
                )

        if player_ok:
            ok_count += 1
        else:
            fail_count += 1

    if players_seen == 0:
        fail_count += 1
        print("FAIL match_id={} 未找到 players_info".format(match_id), flush=True)
    else:
        print(
            "CHECK match_id={} players={} ok={} fail={}".format(
                match_id, players_seen, ok_count, fail_count,
            ),
            flush=True,
        )

    return players_seen, ok_count, fail_count


async def main() -> None:
    parser = argparse.ArgumentParser(description="验证 JJC 对局详情快照拆表保存格式")
    parser.add_argument("--match-id", type=int, default=None, help="只验证单个 match_id")
    parser.add_argument("--limit", type=int, default=5, help="验证最近 N 条 jjc_match_detail，默认 5")
    args = parser.parse_args()

    try:
        uri = _get_mongo_uri()
    except RuntimeError as exc:
        print("错误: {}".format(exc), flush=True)
        sys.exit(1)

    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    client: AsyncIOMotorClient = AsyncIOMotorClient(uri, maxPoolSize=10, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
    except Exception as exc:
        print("MongoDB 连接失败: {}".format(exc), flush=True)
        sys.exit(1)

    db = client[db_name]
    print("MongoDB 连接成功: {}".format(db_name), flush=True)
    print("{} 文档数: {}".format(SOURCE_COLLECTION, await db[SOURCE_COLLECTION].estimated_document_count()), flush=True)
    print("{} 文档数: {}".format(EQUIPMENT_COLLECTION, await db[EQUIPMENT_COLLECTION].estimated_document_count()), flush=True)
    print("{} 文档数: {}".format(TALENT_COLLECTION, await db[TALENT_COLLECTION].estimated_document_count()), flush=True)

    docs = await _load_docs(db, args.match_id, args.limit)
    if not docs:
        print("未找到需要验证的 jjc_match_detail 文档", flush=True)
        client.close()
        sys.exit(1)

    total_players = 0
    total_ok = 0
    total_fail = 0
    for doc in docs:
        players_seen, ok_count, fail_count = await _verify_doc(db, doc)
        total_players += players_seen
        total_ok += ok_count
        total_fail += fail_count

    print()
    print("验证汇总: docs={} players={} ok={} fail={}".format(len(docs), total_players, total_ok, total_fail), flush=True)
    client.close()
    if total_fail:
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
