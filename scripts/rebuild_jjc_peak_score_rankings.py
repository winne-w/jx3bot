#!/usr/bin/env python3
"""Preview, rebuild, or verify current-season peak rankings without changing facts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from motor.motor_asyncio import AsyncIOMotorClient


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAFE_VALIDATION_ERRORS = {
    "only_configured_current_season_is_allowed",
    "invalid_season_history_anchor",
    "requested_anchor_not_in_season_history",
    "no_season_snapshots",
    "snapshot_season_mismatch",
    "invalid_snapshot_context",
}

from src.services.jx3.jjc_peak_score_ranking import (  # noqa: E402
    AGGREGATION_SCOPE,
    SCORE_TYPES,
    JjcPeakScoreRankingService,
)
from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo  # noqa: E402
from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo  # noqa: E402
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo  # noqa: E402


def get_mongo_uri() -> str:
    """Follow explicit environment, runtime override, then config; never log the URI."""
    uri = os.getenv("MONGO_URI")
    if uri:
        return uri
    runtime_config = ROOT / "runtime_config.json"
    if runtime_config.is_file():
        payload = json.loads(runtime_config.read_text(encoding="utf-8"))
        uri = payload.get("MONGO_URI") if isinstance(payload, dict) else None
        if uri:
            return str(uri)
    from config import MONGO_URI

    return str(MONGO_URI)


def get_db(client: Any, db_name: Optional[str]) -> Any:
    if db_name:
        return client[db_name]
    default_db = client.get_default_database(default=None)
    return default_db if default_db is not None else client["jx3bot"]


def get_current_season_config() -> Dict[str, Any]:
    from config import CURRENT_SEASON, CURRENT_SEASON_START

    start = datetime.strptime(str(CURRENT_SEASON_START), "%Y-%m-%d").replace(
        tzinfo=timezone(timedelta(hours=8)),
    )
    return {"current_season": str(CURRENT_SEASON).strip(), "season_start_time": int(start.timestamp())}


def compare_results(old: Optional[Dict[str, Any]], new: Dict[str, Any], start: int) -> Dict[str, int]:
    """Return counts only: do not disclose role names, identifiers, or individual scores."""
    old_items = (old or {}).get("items") or []
    new_items = new.get("items") or []
    old_by_id = {item["global_id"]: item for item in old_items if item.get("global_id")}
    new_by_id = {item["global_id"]: item for item in new_items if item.get("global_id")}
    old_ids, new_ids = set(old_by_id), set(new_by_id)
    return {
        "old_item_count": len(old_items),
        "new_item_count": len(new_items),
        "old_preseason_peak_count": sum(
            1 for item in old_items if (isinstance(item.get("match_time"), int) and not isinstance(item.get("match_time"), bool)) and item["match_time"] < start
        ),
        "old_invalid_time_count": sum(1 for item in old_items if (not isinstance(item.get("match_time"), int) or isinstance(item.get("match_time"), bool))),
        "added_member_count": len(new_ids - old_ids),
        "removed_member_count": len(old_ids - new_ids),
        "changed_score_count": sum(
            1 for identity in old_ids & new_ids if old_by_id[identity].get("score") != new_by_id[identity].get("score")
        ),
    }


def verification_errors(doc: Optional[Dict[str, Any]], context: Dict[str, Any],
                        anchor: int, score_type: str, version: int) -> List[str]:
    if not isinstance(doc, dict):
        return ["missing_result"]
    errors = []
    expected = dict(context, anchor_timestamp=anchor, score_type=score_type, version=version, status="done")
    if any(doc.get(key) != value for key, value in expected.items()):
        errors.append("result_contract_mismatch")
    items = doc.get("items")
    if not isinstance(items, list):
        return errors + ["invalid_items"]
    if (not isinstance(doc.get("item_count"), int) or isinstance(doc.get("item_count"), bool)) or doc["item_count"] != len(items):
        errors.append("item_count_mismatch")
    if len(items) > 1000:
        errors.append("too_many_items")
    identities = set()
    for rank, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append("invalid_item")
            continue
        if (not isinstance(item.get("rank"), int) or isinstance(item.get("rank"), bool)) or item["rank"] != rank:
            errors.append("rank_not_contiguous")
        match_time = item.get("match_time")
        if (not isinstance(match_time, int) or isinstance(match_time, bool)) or not (context["window_start"] <= match_time <= context["window_end"]):
            errors.append("match_outside_window")
        identity = item.get("global_id")
        if not isinstance(identity, str) or not identity or identity in identities:
            errors.append("invalid_or_duplicate_member")
        if isinstance(identity, str):
            identities.add(identity)
    return sorted(set(errors))


async def run(args: argparse.Namespace, db: Any) -> Dict[str, Any]:
    """Run against an injected database; dry-run and verify never initialize indexes or write."""
    config = get_current_season_config()
    season = str(args.season).strip()
    if not season or season != config["current_season"]:
        raise ValueError("only_configured_current_season_is_allowed")
    ranking_repo = JjcRankingStatsRepo(db=db, suppress_errors=False)
    peak_repo = JjcPeakScoreRankingRepo(db=db, suppress_errors=False)
    service = JjcPeakScoreRankingService(
        ranking_stats_repo=ranking_repo, participant_repo=JjcMatchParticipantRepo(db=db),
        peak_repo=peak_repo, current_season=season, season_start_time=config["season_start_time"],
    )
    history = await ranking_repo.list_season_history(season)
    available = set()
    for item in history.get("items") or []:
        anchor = item.get("timestamp")
        if (not isinstance(anchor, int) or isinstance(anchor, bool)) or anchor < config["season_start_time"]:
            raise ValueError("invalid_season_history_anchor")
        available.add(anchor)
    requested = set(args.anchor or [])
    if any((not isinstance(anchor, int) or isinstance(anchor, bool)) or anchor not in available for anchor in requested):
        raise ValueError("requested_anchor_not_in_season_history")
    anchors = sorted(requested or available, reverse=True)
    if not anchors:
        raise ValueError("no_season_snapshots")
    # Validate the complete selection before any apply writes.
    contexts = {}
    for anchor in anchors:
        summary = await ranking_repo.load_summary(anchor)
        if not summary or str(summary.get("current_season") or "").strip() != season:
            raise ValueError("snapshot_season_mismatch")
        context = await service._context(anchor, None)
        if not context or context.get("aggregation_scope") != AGGREGATION_SCOPE:
            raise ValueError("invalid_snapshot_context")
        contexts[anchor] = context

    report: Dict[str, Any] = {"mode": args.mode, "season": season, "anchors": anchors,
                              "results": [], "failed": 0, "completed": 0}
    for anchor in anchors:
        for score_type in SCORE_TYPES:
            row: Dict[str, Any] = {"anchor_timestamp": anchor, "score_type": score_type,
                                   "window_start": contexts[anchor]["window_start"], "window_end": anchor}
            try:
                old = await peak_repo.load_result(anchor_timestamp=anchor, score_type=score_type,
                                                  version=service.version)
                if args.mode == "verify":
                    errors = verification_errors(old, contexts[anchor], anchor, score_type, service.version)
                    row.update(status="failed" if errors else "verified", errors=errors,
                               item_count=len((old or {}).get("items") or []))
                elif args.mode == "apply":
                    new = await service.generate_for_anchor(anchor_timestamp=anchor, score_type=score_type, force=True)
                    if new.get("status") != "done" or new.get("skipped"):
                        row.update(status="failed", errors=["generation_failed"])
                    else:
                        errors = verification_errors(new, contexts[anchor], anchor, score_type, service.version)
                        row.update(compare_results(old, new, config["season_start_time"]))
                        row.update(status="failed" if errors else "done", errors=errors)
                else:
                    new = await service._aggregate(anchor, score_type, service.version, contexts[anchor],
                                                   service.max_items, True)
                    row.update(compare_results(old, new, config["season_start_time"]))
                    row.update(status="preview")
            except Exception as exc:
                # Exception messages can contain connection details or role data.
                row.update(status="failed", error_type=type(exc).__name__)
            report["results"].append(row)
            report["failed" if row["status"] == "failed" else "completed"] += 1
    return report


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="定向预览、重建或校验当前赛季 14 日最高分排名")
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify"), default="dry-run")
    parser.add_argument("--season", required=True, help="必须等于当前配置的赛季名称")
    parser.add_argument("--anchor", type=int, action="append", default=[], help="只处理该锚点，可重复；默认本赛季全部锚点")
    parser.add_argument("--db-name", default=None, help="覆盖 URI 中的数据库名")
    return parser.parse_args(argv)


def exit_code_for_report(report: Dict[str, Any]) -> int:
    return 1 if report.get("failed") else 0


async def _run_connected(args: argparse.Namespace) -> Dict[str, Any]:
    client = AsyncIOMotorClient(get_mongo_uri(), serverSelectionTimeoutMS=8000, maxPoolSize=4)
    try:
        db = get_db(client, args.db_name)
        await db.command("ping")
        return await run(args, db)
    finally:
        client.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        report = asyncio.run(_run_connected(args))
    except Exception as exc:
        report = {"mode": args.mode, "failed": 1, "error_type": type(exc).__name__}
        if isinstance(exc, ValueError) and str(exc) in SAFE_VALIDATION_ERRORS:
            report["error"] = str(exc)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
    return exit_code_for_report(report)


if __name__ == "__main__":
    # NoneBot's default Loguru sink writes to stdout. Keep the command's stdout
    # machine-readable even when repository/service diagnostics are emitted.
    from nonebot import logger
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    raise SystemExit(main())
