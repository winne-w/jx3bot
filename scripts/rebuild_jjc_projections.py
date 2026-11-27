#!/usr/bin/env python3
"""Unified CLI to rebuild JJC match-detail projections (fact / participant / identity)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._common.mongo import (  # noqa: E402
    open_async_client,
    resolve_db_name,
    resolve_mongo_uri,
)
from src.services.jx3.match_detail_fact_projection import (  # noqa: E402
    MatchDetailFactProjectionService,
)
from src.services.jx3.match_detail_identity_projection import (  # noqa: E402
    MatchDetailIdentityProjectionService,
)
from src.services.jx3.match_detail_participant_projection import (  # noqa: E402
    MatchDetailParticipantProjectionService,
)
from src.storage.mongo_repos.jjc_match_fact_repo import JjcMatchFactRepo  # noqa: E402
from src.storage.mongo_repos.jjc_match_participant_repo import (  # noqa: E402
    JjcMatchParticipantRepo,
)
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo  # noqa: E402
from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo  # noqa: E402


VALID_STAGES: Tuple[str, ...] = ("fact", "participant", "identity")
SOURCE_NAME = "rebuild_jjc_projections"


def resolve_stages(stage: str) -> Tuple[str, ...]:
    """Expand a stage selector into an ordered tuple of concrete stage names."""
    normalized = str(stage or "").strip().lower()
    if normalized == "all":
        return VALID_STAGES
    if normalized in VALID_STAGES:
        return (normalized,)
    raise ValueError("Unsupported stage: {!r}".format(stage))


def _normalize_stages(stages: Iterable[str]) -> List[str]:
    if isinstance(stages, str):
        return list(resolve_stages(stages))
    resolved: List[str] = []
    for item in stages:
        for concrete in resolve_stages(item):
            if concrete not in resolved:
                resolved.append(concrete)
    if not resolved:
        raise ValueError("At least one projection stage is required")
    return resolved


def _coerce_positive_match_id(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        raw = value.strip()
        if raw.isascii() and raw.isdigit():
            parsed = int(raw)
            return parsed if parsed > 0 else None
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="统一重建 JJC 对局详情投影（fact / participant / identity）",
    )
    parser.add_argument(
        "--stage",
        choices=("fact", "participant", "identity", "all"),
        default="all",
        help="要执行的投影阶段（默认 all）",
    )
    parser.add_argument(
        "--match-id",
        dest="match_ids",
        action="append",
        type=int,
        default=None,
        help="指定重建的 match_id，可重复传入",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多处理的对局数；0 表示不限",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="只统计不写入",
    )
    parser.add_argument(
        "--mongo-uri",
        default=None,
        help="MongoDB URI（可选，省略时按默认规则解析）",
    )
    parser.add_argument(
        "--db-name",
        default=None,
        help="数据库名（可选，省略时从 URI 解析或使用默认库名）",
    )
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if args.limit < 0:
        raise ValueError("--limit must be a non-negative integer")
    if args.match_ids is not None:
        for mid in args.match_ids:
            if mid <= 0:
                raise ValueError("--match-id must be a positive integer")
    return args


def _build_query(match_ids: Optional[Iterable[int]]) -> Dict[str, Any]:
    if match_ids is None:
        return {}
    normalized = [int(mid) for mid in match_ids]
    if not normalized:
        return {}
    if len(normalized) == 1:
        return {"match_id": normalized[0]}
    return {"match_id": {"$in": normalized}}


async def _fetch_match_docs(
    db: Any,
    *,
    match_ids: Optional[Iterable[int]],
    limit: int,
) -> List[Dict[str, Any]]:
    query = _build_query(match_ids)
    cursor = db.jjc_match_detail.find(query)
    if limit > 0 and hasattr(cursor, "limit"):
        cursor = cursor.limit(limit)
    if hasattr(cursor, "to_list"):
        docs = await cursor.to_list(length=limit if limit > 0 else None)
    else:
        docs = []
        async for doc in cursor:
            docs.append(doc)
            if limit > 0 and len(docs) >= limit:
                break
    if limit > 0:
        return list(docs[:limit])
    return list(docs)


async def rebuild_projections(
    db: Any,
    *,
    stages: Iterable[str],
    match_ids: Optional[Iterable[int]] = None,
    limit: int = 0,
    dry_run: bool = False,
    fact_projector: Optional[Any] = None,
    participant_projector: Optional[Any] = None,
    identity_projector: Optional[Any] = None,
) -> Dict[str, Any]:
    """Rebuild selected JJC match-detail projections from ``db.jjc_match_detail``."""
    selected_stages = _normalize_stages(stages)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer")

    docs = await _fetch_match_docs(db, match_ids=match_ids, limit=limit)

    if not dry_run:
        sync_repo: Optional[JjcSyncRepo] = None
        if "fact" in selected_stages and fact_projector is None:
            fact_projector = MatchDetailFactProjectionService(
                fact_repo=JjcMatchFactRepo(db=db),
            )
        if "participant" in selected_stages and participant_projector is None:
            sync_repo = JjcSyncRepo(db=db)
            participant_projector = MatchDetailParticipantProjectionService(
                participant_repo=JjcMatchParticipantRepo(db=db),
                sync_repo=sync_repo,
            )
        if "identity" in selected_stages and identity_projector is None:
            if sync_repo is None:
                sync_repo = JjcSyncRepo(db=db)
            identity_projector = MatchDetailIdentityProjectionService(
                identity_repo=RoleIdentityRepo(db=db),
                sync_repo=sync_repo,
            )

    summary: Dict[str, Any] = {
        "dry_run": bool(dry_run),
        "stages": list(selected_stages),
        "scanned": 0,
        "skipped_invalid_match_id": 0,
        "stage_stats": {
            stage: {"processed": 0, "would_process": 0, "failed": 0}
            for stage in selected_stages
        },
    }

    for doc in docs:
        summary["scanned"] += 1
        if not isinstance(doc, dict):
            summary["skipped_invalid_match_id"] += 1
            continue
        match_id = _coerce_positive_match_id(doc.get("match_id"))
        if match_id is None:
            summary["skipped_invalid_match_id"] += 1
            continue

        if "data" in doc:
            payload: Dict[str, Any] = {
                "cached_at": doc.get("cached_at"),
                "data": doc.get("data"),
            }
        else:
            payload = dict(doc)

        for stage in selected_stages:
            stage_stat = summary["stage_stats"][stage]
            if dry_run:
                stage_stat["would_process"] += 1
                continue
            try:
                if stage == "fact":
                    result = await fact_projector.project_payload(
                        match_id=match_id,
                        payload=payload,
                        source=SOURCE_NAME,
                    )
                elif stage == "participant":
                    result = await participant_projector.project_payload(
                        match_id=match_id,
                        payload=payload,
                        source=SOURCE_NAME,
                    )
                elif stage == "identity":
                    wrapped_data = payload.get("data")
                    identity_payload = (
                        wrapped_data if isinstance(wrapped_data, dict) else payload
                    )
                    result = await identity_projector.project_payload(
                        match_id=match_id,
                        payload=identity_payload,
                        source=SOURCE_NAME,
                    )
                else:
                    raise ValueError("Unsupported stage: {!r}".format(stage))

                if isinstance(result, dict) and result.get("error") is not None:
                    stage_stat["failed"] += 1
                else:
                    stage_stat["processed"] += 1
            except Exception:
                stage_stat["failed"] += 1

    return summary


async def _run_cli(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    uri = resolve_mongo_uri(args.mongo_uri)
    db_name = args.db_name or resolve_db_name(uri)
    client = open_async_client(uri)
    try:
        db = client[db_name]
        summary = await rebuild_projections(
            db,
            stages=resolve_stages(args.stage),
            match_ids=args.match_ids,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        client.close()


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(_run_cli(argv))


if __name__ == "__main__":
    raise SystemExit(main())
