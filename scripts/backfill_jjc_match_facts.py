#!/usr/bin/env python3
"""Safely rebuild JJC match facts from persisted match-detail source documents."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.jx3.jjc_match_fact import (  # noqa: E402
    MATCH_FACT_SOURCE_PROJECTION,
    build_match_fact,
    match_fact_source_payload,
    normalize_positive_int,
)
from src.services.jx3.match_detail_fact_projection import MATCH_FACT_SCHEMA_VERSION  # noqa: E402
from src.storage.mongo_repos.jjc_match_fact_repo import JjcMatchFactRepo  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from pymongo.errors import ConfigurationError  # noqa: E402


FactBuilder = Callable[[Any, Dict[str, Any], int], Dict[str, Any]]
CAS_STATUSES = ("inserted", "updated", "tombstoned", "skipped_old", "conflict", "noop")


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def get_mongo_uri() -> str:
    runtime_config = ROOT / "runtime_config.json"
    if runtime_config.is_file():
        try:
            value = json.loads(runtime_config.read_text(encoding="utf-8")).get("MONGO_URI")
            if value:
                return str(value)
        except Exception:
            pass
    try:
        from config import MONGO_URI
        if MONGO_URI:
            return str(MONGO_URI)
    except Exception:
        pass
    value = os.getenv("MONGO_URI")
    if value:
        return value
    raise RuntimeError("Mongo URI is not configured")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="回填或核验 JJC 对局事实投影")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI（仅用于本次进程，不输出）")
    parser.add_argument("--db-name", default=None, help="数据库名；省略时使用 URI 中数据库或 jx3bot")
    parser.add_argument("--resume-after-match-id", type=int, default=None, help="仅处理该正整数 match_id 之后的数据")
    parser.add_argument("--batch-size", type=int, default=500, help="每批详情数，默认 500")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条详情；0 表示不限")
    parser.add_argument("--dry-run", action="store_true", help="只构建和统计，不写入（默认）")
    parser.add_argument("--apply", action="store_true", help="执行投影写入")
    parser.add_argument("--yes", action="store_true", help="与 --apply 同时提供才允许写入")
    parser.add_argument("--verify-only", action="store_true", help="只读核验事实投影，不写入")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="仅投影当前不存在的 match_id；用于补齐乱序新增主详情",
    )
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.apply and not args.yes:
        raise ValueError("--apply requires --yes")
    if args.apply and args.verify_only:
        raise ValueError("--apply cannot be used with --verify-only")
    if args.apply and args.dry_run:
        raise ValueError("--apply cannot be used with --dry-run")
    if args.missing_only and not args.apply:
        raise ValueError("--missing-only requires --apply --yes")
    if args.resume_after_match_id is not None and normalize_positive_int(args.resume_after_match_id) is None:
        raise ValueError("--resume-after-match-id must be a positive integer")
    if isinstance(args.batch_size, bool) or not isinstance(args.batch_size, int) or args.batch_size <= 0:
        raise ValueError("--batch-size must be a positive integer")
    if isinstance(args.limit, bool) or not isinstance(args.limit, int) or args.limit < 0:
        raise ValueError("--limit must be a non-negative integer")
    args.dry_run = not args.apply and not args.verify_only
    return args


def build_query(args: argparse.Namespace) -> Dict[str, Any]:
    if args.resume_after_match_id is None:
        return {}
    return {"match_id": {"$gt": args.resume_after_match_id}}


def _empty_backfill_stats() -> Dict[str, int]:
    stats = {
        "scanned": 0,
        "invalid_match_id": 0,
        "active": 0,
        "inactive": 0,
        "structural_skipped": 0,
        "score_incomplete": 0,
        "would_apply": 0,
        "build_failed": 0,
        "apply_failed": 0,
        "blocking_failure": 0,
        "last_successful_match_id": 0,
    }
    for status in CAS_STATUSES:
        stats[status] = 0
    return stats


def _empty_verify_stats() -> Dict[str, int]:
    return {
        "source_scanned": 0,
        "missing": 0,
        "orphan": 0,
        "orphan_check_skipped": 0,
        "should_be_inactive": 0,
        "hash_mismatch": 0,
        "schema_outdated": 0,
        "build_failed": 0,
    }


def _source_payload(document: Mapping[str, Any]) -> Dict[str, Any]:
    return match_fact_source_payload(document)


def _is_incomplete_active(fact: Mapping[str, Any]) -> bool:
    if fact.get("active") is not True:
        return False
    return not bool((fact.get("team1") or {}).get("score_complete")) or not bool(
        (fact.get("team2") or {}).get("score_complete")
    )


def _predicted_cas_status(incoming: Mapping[str, Any], current: Optional[Mapping[str, Any]]) -> str:
    incoming = JjcMatchFactRepo._normalize_projection(dict(incoming))
    if current is None:
        return "tombstoned" if incoming.get("active") is False else "inserted"
    if not JjcMatchFactRepo._current_is_valid(dict(current)):
        return "tombstoned" if incoming.get("active") is False else "updated"
    current_time = current.get("source_cached_at")
    incoming_time = incoming.get("source_cached_at")
    if not isinstance(current_time, (int, float)) or isinstance(current_time, bool):
        return "tombstoned" if incoming.get("active") is False else "updated"
    if incoming_time < current_time:
        return "skipped_old"
    if incoming_time == current_time:
        if incoming.get("source_hash") != current.get("source_hash"):
            return "conflict"
        if incoming.get("schema_version", 0) <= current.get("schema_version", 0):
            return "noop"
    return "tombstoned" if incoming.get("active") is False else "updated"


async def process_batch(
    *,
    repo: Any,
    docs: Iterable[Dict[str, Any]],
    dry_run: bool,
    verify_only: bool,
    fact_builder: FactBuilder = build_match_fact,
) -> Dict[str, int]:
    """Build one source batch and optionally apply the repository CAS operation."""
    if verify_only:
        raise ValueError("verify-only batches must use verify_batch")
    stats = _empty_backfill_stats()
    prepared = []
    for document in docs:
        stats["scanned"] += 1
        match_id = normalize_positive_int(document.get("match_id"))
        if match_id is None:
            stats["invalid_match_id"] += 1
            continue
        try:
            fact = fact_builder(match_id, _source_payload(document), MATCH_FACT_SCHEMA_VERSION)
        except Exception as exc:
            stats["build_failed"] += 1
            stats["blocking_failure"] = 1
            _log("[FAIL] match_id={} stage=build error_type={}".format(match_id, type(exc).__name__))
            break
        if fact.get("active") is True:
            stats["active"] += 1
        else:
            stats["inactive"] += 1
            if fact.get("invalid_reason") != "unavailable":
                stats["structural_skipped"] += 1
        if _is_incomplete_active(fact):
            stats["score_incomplete"] += 1
        stats["would_apply"] += 1
        prepared.append((match_id, fact))

    if dry_run:
        try:
            states = await repo.get_projection_states([match_id for match_id, _ in prepared])
        except Exception as exc:
            stats["apply_failed"] += len(prepared)
            stats["blocking_failure"] = 1
            _log("[FAIL] match_ids={} stage=dry_run_states error_type={}".format(
                ",".join(str(match_id) for match_id, _ in prepared), type(exc).__name__,
            ))
            return stats
        for match_id, fact in prepared:
            try:
                status = _predicted_cas_status(fact, states.get(match_id))
            except Exception as exc:
                stats["apply_failed"] += 1
                stats["blocking_failure"] = 1
                _log("[FAIL] match_id={} stage=dry_run_predict error_type={}".format(match_id, type(exc).__name__))
                break
            stats[status] += 1
            if status == "conflict":
                stats["blocking_failure"] = 1
                break
            stats["last_successful_match_id"] = match_id
        return stats

    for match_id, fact in prepared:
        try:
            status = await repo.apply_projection(fact)
        except Exception as exc:
            stats["apply_failed"] += 1
            stats["blocking_failure"] = 1
            _log("[FAIL] match_id={} stage=apply error_type={}".format(match_id, type(exc).__name__))
            break
        if status not in CAS_STATUSES:
            stats["apply_failed"] += 1
            stats["blocking_failure"] = 1
            _log("[FAIL] match_id={} stage=apply_status error_type=UnexpectedStatus".format(match_id))
            break
        stats[status] += 1
        if status == "conflict":
            stats["blocking_failure"] = 1
            break
        stats["last_successful_match_id"] = match_id
    return stats


async def verify_batch(
    *,
    repo: Any,
    docs: Iterable[Dict[str, Any]],
    fact_builder: FactBuilder = build_match_fact,
    projection_states: Optional[Mapping[int, Dict[str, Any]]] = None,
    scoped: bool = False,
) -> Dict[str, int]:
    """Compare source facts to persisted projections without performing writes."""
    documents = list(docs)
    stats = _empty_verify_stats()
    source_ids = set()
    expected: Dict[int, Dict[str, Any]] = {}
    for document in documents:
        match_id = normalize_positive_int(document.get("match_id"))
        if match_id is None:
            continue
        source_ids.add(match_id)
        stats["source_scanned"] += 1
        try:
            expected[match_id] = fact_builder(match_id, _source_payload(document), MATCH_FACT_SCHEMA_VERSION)
        except Exception:
            stats["build_failed"] += 1
    if projection_states is None:
        projection_states = await repo.get_projection_states(sorted(source_ids))

    for match_id in source_ids:
        current = projection_states.get(match_id)
        if current is None:
            stats["missing"] += 1
            continue
        wanted = expected.get(match_id)
        if wanted is None:
            continue
        if wanted.get("active") is False and current.get("active") is not False:
            stats["should_be_inactive"] += 1
        if current.get("source_hash") != wanted.get("source_hash"):
            stats["hash_mismatch"] += 1
        schema_version = current.get("schema_version")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version < MATCH_FACT_SCHEMA_VERSION
        ):
            stats["schema_outdated"] += 1
    if scoped:
        stats["orphan_check_skipped"] = 1
    else:
        stats["orphan"] = sum(1 for match_id in projection_states if match_id not in source_ids)
    return stats


def merge_stats(total: Dict[str, int], delta: Mapping[str, int]) -> None:
    for key, value in delta.items():
        if key == "last_successful_match_id":
            total[key] = max(total.get(key, 0), value)
            continue
        total[key] = total.get(key, 0) + value


def _batch_range(docs: Iterable[Dict[str, Any]]) -> str:
    match_ids = [normalize_positive_int(doc.get("match_id")) for doc in docs]
    valid_ids = [match_id for match_id in match_ids if match_id is not None]
    return "{}-{}".format(min(valid_ids), max(valid_ids)) if valid_ids else "unknown"


async def _count_orphans_streaming(db: Any, batch_size: int) -> int:
    """Read fact IDs and source existence in bounded batches."""
    orphan_count = 0
    pending: List[int] = []

    async def count_pending(match_ids: List[int]) -> int:
        existing = set()
        source_cursor = db.jjc_match_detail.find(
            {"match_id": {"$in": match_ids}}, {"match_id": 1}
        ).batch_size(batch_size)
        async for source in source_cursor:
            if isinstance(source, dict):
                match_id = normalize_positive_int(source.get("match_id"))
                if match_id is not None:
                    existing.add(match_id)
        return sum(1 for match_id in match_ids if match_id not in existing)

    fact_cursor = db.jjc_match_facts.find({}, {"match_id": 1}).batch_size(batch_size)
    async for fact in fact_cursor:
        if not isinstance(fact, dict):
            continue
        match_id = normalize_positive_int(fact.get("match_id"))
        if match_id is None:
            continue
        pending.append(match_id)
        if len(pending) >= batch_size:
            orphan_count += await count_pending(pending)
            pending = []
    if pending:
        orphan_count += await count_pending(pending)
    return orphan_count


async def _run_with_database(
    args: argparse.Namespace,
    database: Any,
    repo: Any,
    fact_builder: FactBuilder,
) -> Dict[str, int]:
    """Run a bounded dry-run/apply backfill against one selected database."""
    fact_repo = repo if repo is not None else JjcMatchFactRepo(db=database)
    projection = MATCH_FACT_SOURCE_PROJECTION
    async def execute() -> Dict[str, int]:
        cursor = database.jjc_match_detail.find(
            build_query(args), projection, no_cursor_timeout=True
        ).sort("match_id", 1).batch_size(args.batch_size)
        docs: List[Dict[str, Any]] = []
        seen = 0
        scoped_verify = bool(args.resume_after_match_id is not None or args.limit)
        verify_total = _empty_verify_stats()
        async def process_verify_docs(batch: List[Dict[str, Any]]) -> None:
            batch_ids = [normalize_positive_int(doc.get("match_id")) for doc in batch]
            states = await fact_repo.get_projection_states([match_id for match_id in batch_ids if match_id is not None])
            delta = await verify_batch(
                repo=fact_repo, docs=batch, projection_states=states,
                fact_builder=fact_builder, scoped=True,
            )
            merge_stats(verify_total, delta)
            _log("[BATCH] range={} delta={} total={}".format(
                _batch_range(batch), json.dumps(delta, ensure_ascii=False, sort_keys=True),
                json.dumps(verify_total, ensure_ascii=False, sort_keys=True),
            ))

        async def process_backfill_docs(batch: List[Dict[str, Any]]) -> Dict[str, int]:
            selected = batch
            if args.missing_only:
                match_ids = []
                for document in batch:
                    match_id = normalize_positive_int(document.get("match_id"))
                    if match_id is not None:
                        match_ids.append(match_id)
                try:
                    states = await fact_repo.get_projection_states(match_ids)
                except Exception as exc:
                    delta = _empty_backfill_stats()
                    delta["apply_failed"] = len(match_ids)
                    delta["blocking_failure"] = 1
                    _log("[FAIL] match_ids={} stage=missing_only_states error_type={}".format(
                        ",".join(str(match_id) for match_id in match_ids), type(exc).__name__,
                    ))
                    return delta
                selected = [
                    document for document in batch
                    if (normalize_positive_int(document.get("match_id")) is not None
                        and normalize_positive_int(document.get("match_id")) not in states)
                ]
            return await process_batch(
                repo=fact_repo, docs=selected, dry_run=args.dry_run, verify_only=False,
                fact_builder=fact_builder,
            )

        async for document in cursor:
            if args.limit and seen >= args.limit:
                break
            if not isinstance(document, dict):
                continue
            seen += 1
            docs.append(document)
            if len(docs) >= args.batch_size:
                if args.verify_only:
                    await process_verify_docs(docs)
                    docs = []
                    continue
                delta = await process_backfill_docs(docs)
                if "total" not in locals():
                    total = _empty_backfill_stats()
                merge_stats(total, delta)
                _log("[BATCH] range={} delta={} total={}".format(
                    _batch_range(docs), json.dumps(delta, ensure_ascii=False, sort_keys=True),
                    json.dumps(total, ensure_ascii=False, sort_keys=True),
                ))
                if delta["blocking_failure"]:
                    return total
                docs = []
        if args.verify_only:
            if docs:
                await process_verify_docs(docs)
            verify_total["orphan_check_skipped"] = 1 if scoped_verify else 0
            if not scoped_verify:
                verify_total["orphan"] = await _count_orphans_streaming(database, args.batch_size)
            return verify_total
        if "total" not in locals():
            total = _empty_backfill_stats()
        if docs:
            delta = await process_backfill_docs(docs)
            merge_stats(total, delta)
            _log("[BATCH] range={} delta={} total={}".format(
                _batch_range(docs), json.dumps(delta, ensure_ascii=False, sort_keys=True),
                json.dumps(total, ensure_ascii=False, sort_keys=True),
            ))
        return total
    return await execute()


async def run(
    args: argparse.Namespace,
    db: Any = None,
    repo: Any = None,
    fact_builder: FactBuilder = build_match_fact,
    client_factory: Any = AsyncIOMotorClient,
) -> Dict[str, int]:
    """Run a bounded dry-run/apply backfill or a fully read-only verification."""
    args = validate_args(args)
    client = None
    try:
        if db is not None:
            database = db
        else:
            client = client_factory(args.mongo_uri or get_mongo_uri(), serverSelectionTimeoutMS=8000)
            if args.db_name:
                database = client[args.db_name]
            else:
                try:
                    database = client.get_default_database(default=None)
                except ConfigurationError:
                    database = client["jx3bot"]
                if database is None:
                    database = client["jx3bot"]
        return await _run_with_database(args, database, repo, fact_builder)
    finally:
        if client is not None:
            client.close()


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = validate_args(parse_args(argv))
    except ValueError as exc:
        raise SystemExit(str(exc))
    stats = asyncio.run(run(args))
    _log(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
