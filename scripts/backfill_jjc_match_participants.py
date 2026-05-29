#!/usr/bin/env python3
"""Backfill jjc_match_participants from cached jjc_match_detail documents."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase  # noqa: E402

from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo  # noqa: E402


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


def get_db(client: AsyncIOMotorClient, db_name: Optional[str]) -> AsyncIOMotorDatabase:
    if db_name:
        return client[db_name]
    default_db = client.get_default_database(default=None)
    if default_db is not None:
        return default_db
    return client["jx3bot"]


def build_query(args: argparse.Namespace) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if args.match_id is not None:
        query["match_id"] = int(args.match_id)
    elif args.resume_after_match_id is not None:
        query["match_id"] = {"$gt": int(args.resume_after_match_id)}
    return query


async def load_seen_docs(db: AsyncIOMotorDatabase, match_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not match_ids:
        return {}
    cursor = db.jjc_sync_match_seen.find({"match_id": {"$in": match_ids}})
    docs = await cursor.to_list(length=None)
    result: Dict[int, Dict[str, Any]] = {}
    for doc in docs:
        mid = JjcMatchParticipantRepo._coerce_int(doc.get("match_id"))
        if mid is not None:
            result[mid] = doc
    return result


async def process_batch(
    *,
    repo: JjcMatchParticipantRepo,
    db: AsyncIOMotorDatabase,
    docs: List[Dict[str, Any]],
    dry_run: bool,
    verify_only: bool,
) -> Dict[str, int]:
    stats = {
        "seen": 0,
        "projectable_matches": 0,
        "participant_rows": 0,
        "written_matches": 0,
        "cleared_matches": 0,
        "verified_ok": 0,
        "verified_diff": 0,
        "failed": 0,
        "skipped_bad_match_id": 0,
    }
    match_ids: List[int] = []
    for doc in docs:
        mid = JjcMatchParticipantRepo._coerce_int(doc.get("match_id"))
        if mid is not None:
            match_ids.append(mid)
    seen_by_match_id = await load_seen_docs(db, match_ids)

    for doc in docs:
        stats["seen"] += 1
        match_id = JjcMatchParticipantRepo._coerce_int(doc.get("match_id"))
        if match_id is None:
            stats["skipped_bad_match_id"] += 1
            continue
        try:
            payload = {"cached_at": doc.get("cached_at"), "data": doc.get("data")}
            participants = repo.build_participants_from_match_detail(
                match_id,
                payload,
                seen_doc=seen_by_match_id.get(match_id),
                detail_source=JjcMatchParticipantRepo.DETAIL_SOURCE_MANUAL,
            )
        except Exception as exc:
            stats["failed"] += 1
            _log("[FAIL] match_id={} stage=build error={}".format(match_id, exc))
            continue
        if participants:
            stats["projectable_matches"] += 1
            stats["participant_rows"] += len(participants)

        if verify_only:
            try:
                existing = await db.jjc_match_participants.count_documents({
                    "match_id": match_id,
                    "detail_available": True,
                })
            except Exception as exc:
                stats["failed"] += 1
                _log("[FAIL] match_id={} stage=verify error={}".format(match_id, exc))
                continue
            if existing == len(participants):
                stats["verified_ok"] += 1
            else:
                stats["verified_diff"] += 1
                _log("[DIFF] match_id={} expected_rows={} actual_rows={}".format(
                    match_id, len(participants), existing,
                ))
            continue

        if dry_run:
            _log("[DRY_RUN] match_id={} participant_rows={}".format(match_id, len(participants)))
            continue

        try:
            written = await repo.replace_match_participants(match_id, participants)
        except Exception as exc:
            stats["failed"] += 1
            _log("[FAIL] match_id={} stage=write error={}".format(match_id, exc))
            continue
        if written:
            stats["written_matches"] += 1
        elif not participants:
            stats["cleared_matches"] += 1

    return stats


def merge_stats(total: Dict[str, int], delta: Dict[str, int]) -> None:
    for key, value in delta.items():
        total[key] = total.get(key, 0) + value


def get_match_id_range(docs: List[Dict[str, Any]]) -> str:
    match_ids: List[int] = []
    for doc in docs:
        match_id = JjcMatchParticipantRepo._coerce_int(doc.get("match_id"))
        if match_id is not None:
            match_ids.append(match_id)
    if not match_ids:
        return "unknown"
    return "{}-{}".format(min(match_ids), max(match_ids))


def get_mode(args: argparse.Namespace) -> str:
    if args.verify_only:
        return "verify_only"
    if args.dry_run:
        return "dry_run"
    return "apply"


async def process_logged_batch(
    *,
    repo: JjcMatchParticipantRepo,
    db: AsyncIOMotorDatabase,
    docs: List[Dict[str, Any]],
    batch_no: int,
    total: Dict[str, int],
    args: argparse.Namespace,
) -> None:
    match_id_range = get_match_id_range(docs)
    _log("[BATCH_START] batch={} docs={} match_id_range={} mode={}".format(
        batch_no, len(docs), match_id_range, get_mode(args),
    ))
    delta = await process_batch(
        repo=repo,
        db=db,
        docs=docs,
        dry_run=args.dry_run,
        verify_only=args.verify_only,
    )
    merge_stats(total, delta)
    _log("[BATCH_DONE] batch={} docs={} match_id_range={} delta={} total={}".format(
        batch_no,
        len(docs),
        match_id_range,
        json.dumps(delta, ensure_ascii=False, sort_keys=True),
        json.dumps(total, ensure_ascii=False, sort_keys=True),
    ))


async def run(args: argparse.Namespace) -> Dict[str, int]:
    client = None
    try:
        client = AsyncIOMotorClient(args.mongo_uri or get_mongo_uri(), serverSelectionTimeoutMS=8000)
        db = get_db(client, args.db_name)
        repo = JjcMatchParticipantRepo(db=db)
        query = build_query(args)
        projection = {
            "match_id": 1,
            "cached_at": 1,
            "data.detail": 1,
            "data.unavailable": 1,
            "data.match_id": 1,
            "data.match_time": 1,
            "data.start_time": 1,
        }
        batch_size = max(1, int(args.batch_size))
        limit = max(0, int(args.limit or 0))
        cursor = db.jjc_match_detail.find(query, projection).sort("match_id", 1).batch_size(batch_size)
        stats: Dict[str, int] = {}
        batch: List[Dict[str, Any]] = []
        batch_no = 0

        async for doc in cursor:
            if limit and stats.get("seen", 0) + len(batch) >= limit:
                break
            batch.append(doc)
            if len(batch) >= batch_size:
                batch_no += 1
                await process_logged_batch(
                    repo=repo,
                    db=db,
                    docs=batch,
                    batch_no=batch_no,
                    total=stats,
                    args=args,
                )
                batch = []

        if batch:
            batch_no += 1
            await process_logged_batch(
                repo=repo,
                db=db,
                docs=batch,
                batch_no=batch_no,
                total=stats,
                args=args,
            )
        return stats
    finally:
        if client is not None:
            client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填 jjc_match_participants 参与者投影表")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI；默认读取 runtime_config/config/env")
    parser.add_argument("--db-name", default=None, help="数据库名；默认从 MongoDB URI 解析")
    parser.add_argument("--match-id", type=int, default=None, help="只处理指定 match_id")
    parser.add_argument("--resume-after-match-id", type=int, default=None, help="按 match_id 升序从该值之后继续")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个详情文档；0 表示不限制")
    parser.add_argument("--batch-size", type=int, default=200, help="批大小，默认 200")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写库；默认行为")
    parser.add_argument("--apply", action="store_true", help="执行写库")
    parser.add_argument("--yes", action="store_true", help="与 --apply 配合确认写库")
    parser.add_argument("--verify-only", action="store_true", help="只校验现有投影行数，不写库")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.match_id is not None and args.resume_after_match_id is not None:
        raise SystemExit("--match-id and --resume-after-match-id cannot be used together")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.apply and not args.yes:
        raise SystemExit("--apply requires --yes")
    if args.apply and args.dry_run:
        raise SystemExit("--apply cannot be used with --dry-run")
    if args.verify_only and args.apply:
        raise SystemExit("--verify-only cannot be used with --apply")
    args.dry_run = (not args.apply and not args.verify_only) or args.dry_run

    stats = asyncio.run(run(args))
    _log(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
