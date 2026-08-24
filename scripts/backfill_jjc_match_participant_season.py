#!/usr/bin/env python3
"""Backfill current-season ownership on JJC participant projections."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


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


def parse_season_start_timestamp(season_start: str) -> int:
    beijing_tz = timezone(timedelta(hours=8))
    return int(datetime.strptime(season_start, "%Y-%m-%d").replace(tzinfo=beijing_tz).timestamp())


def build_season_update(
    match_time: Any,
    current_season: str,
    season_start_time: int,
) -> Dict[str, Dict[str, Optional[str]]]:
    normalized_match_time = _coerce_int(match_time)
    season_id = current_season if normalized_match_time is not None and normalized_match_time >= season_start_time else None
    return {"$set": {"season_id": season_id}}


def get_mongo_uri() -> str:
    runtime_config = ROOT / "runtime_config.json"
    if runtime_config.is_file():
        try:
            payload = json.loads(runtime_config.read_text(encoding="utf-8"))
            uri = payload.get("MONGO_URI") if isinstance(payload, dict) else None
            if uri:
                return str(uri)
        except Exception:
            pass

    from config import MONGO_URI

    return str(os.getenv("MONGO_URI") or MONGO_URI)


def get_db(client: AsyncIOMotorClient, db_name: Optional[str]) -> AsyncIOMotorDatabase:
    if db_name:
        return client[db_name]
    default_db = client.get_default_database(default=None)
    if default_db is not None:
        return default_db
    return client["jx3bot"]


def get_current_season_config() -> Dict[str, Any]:
    from config import CURRENT_SEASON, CURRENT_SEASON_START

    return {
        "current_season": str(CURRENT_SEASON).strip(),
        "season_start": str(CURRENT_SEASON_START).strip(),
        "season_start_time": parse_season_start_timestamp(str(CURRENT_SEASON_START).strip()),
    }


async def flush_operations(collection: Any, operations: List[UpdateOne], stats: Dict[str, int]) -> None:
    if not operations:
        return
    try:
        result = await collection.bulk_write(operations, ordered=False)
        stats["written"] += int(getattr(result, "modified_count", 0) or 0)
    except BulkWriteError as exc:
        details = exc.details or {}
        stats["written"] += int(details.get("nModified", 0) or 0)
        stats["failed"] += len(details.get("writeErrors") or []) or len(operations)
        _log("JJC participant season backfill bulk write failed: {}".format(exc))
    except Exception as exc:
        stats["failed"] += len(operations)
        _log("JJC participant season backfill bulk write failed: {}".format(exc))


def exit_code_for_stats(stats: Dict[str, int]) -> int:
    return 1 if int(stats.get("failed", 0) or 0) > 0 else 0


async def run(args: argparse.Namespace) -> Dict[str, int]:
    config = get_current_season_config()
    current_season = config["current_season"]
    season_start_time = config["season_start_time"]
    if not current_season:
        raise RuntimeError("CURRENT_SEASON 不能为空")

    client = AsyncIOMotorClient(args.mongo_uri or get_mongo_uri(), serverSelectionTimeoutMS=8000)
    try:
        db = get_db(client, args.db_name)
        await db.command("ping")
        collection = db.jjc_match_participants
        stats = {
            "scanned": 0,
            "current_season_rows": 0,
            "unassigned_rows": 0,
            "would_write": 0,
            "written": 0,
            "mismatched": 0,
            "failed": 0,
        }
        batch_size = max(1, int(args.batch_size))
        operations: List[UpdateOne] = []
        cursor = collection.find(
            {"match_type": 3},
            {"_id": 1, "match_time": 1, "season_id": 1},
        ).batch_size(batch_size)

        async for doc in cursor:
            stats["scanned"] += 1
            update = build_season_update(doc.get("match_time"), current_season, season_start_time)
            expected = update["$set"]["season_id"]
            if expected is None:
                stats["unassigned_rows"] += 1
            else:
                stats["current_season_rows"] += 1
            if doc.get("season_id") == expected:
                continue
            stats["mismatched"] += 1
            if args.verify_only:
                continue
            stats["would_write"] += 1
            if args.apply:
                operations.append(UpdateOne({"_id": doc["_id"]}, update))
                if len(operations) >= batch_size:
                    await flush_operations(collection, operations, stats)
                    operations = []

        if operations:
            await flush_operations(collection, operations, stats)
        _log(
            "JJC participant season backfill: current_season={} season_start={} season_start_time={} mode={}".format(
                current_season,
                config["season_start"],
                season_start_time,
                "verify_only" if args.verify_only else ("apply" if args.apply else "dry_run"),
            )
        )
        return stats
    finally:
        client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填 JJC 玩家对局投影的当前赛季字段")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI；默认读取 runtime_config/config/env")
    parser.add_argument("--db-name", default=None, help="数据库名；默认从 MongoDB URI 解析")
    parser.add_argument("--batch-size", type=int, default=500, help="批大小，默认 500")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库；默认行为")
    parser.add_argument("--apply", action="store_true", help="执行写库")
    parser.add_argument("--yes", action="store_true", help="与 --apply 配合确认写库")
    parser.add_argument("--verify-only", action="store_true", help="只校验赛季字段，不写库")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")
    if args.apply and not args.yes:
        raise SystemExit("--apply requires --yes")
    if args.apply and args.dry_run:
        raise SystemExit("--apply cannot be used with --dry-run")
    if args.apply and args.verify_only:
        raise SystemExit("--apply cannot be used with --verify-only")

    stats = asyncio.run(run(args))
    _log(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return exit_code_for_stats(stats)


if __name__ == "__main__":
    raise SystemExit(main())
