#!/usr/bin/env python3
"""Read-only explain and capacity checks for JJC matchup fact queries."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bson import BSON


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from pymongo.errors import ConfigurationError  # noqa: E402
from src.services.jx3.jjc_match_fact import (  # noqa: E402
    MATCH_FACT_SOURCE_PROJECTION,
    build_match_fact,
    match_fact_source_payload,
    normalize_positive_int,
)
from src.services.jx3.jjc_matchup import JjcMatchupService  # noqa: E402
from src.services.jx3.match_detail_fact_projection import MATCH_FACT_SCHEMA_VERSION  # noqa: E402
from src.storage.mongo_repos.jjc_match_fact_repo import JjcMatchFactRepo  # noqa: E402


COLLECTION_NAME = "jjc_match_facts"
SECONDS_PER_DAY = 24 * 60 * 60


def _load_score_limits() -> Dict[str, int]:
    """Load score bounds from the same public contract as the matchup API."""
    limits = JjcMatchupService(None).get_meta().get("limits")
    if not isinstance(limits, dict):
        raise RuntimeError("JJC matchup metadata limits are unavailable")
    score_min, score_max = limits.get("score_min"), limits.get("score_max")
    if (
        isinstance(score_min, bool) or not isinstance(score_min, int)
        or isinstance(score_max, bool) or not isinstance(score_max, int)
        or score_min < 0 or score_min >= score_max
    ):
        raise RuntimeError("JJC matchup metadata score limits are invalid")
    return {"score_min": score_min, "score_max": score_max}


SCORE_LIMITS = _load_score_limits()


def get_mongo_uri() -> str:
    """Resolve the URI in the same order as the fact-backfill script."""
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
    parser = argparse.ArgumentParser(description="只读检查 JJC 对阵查询 explain 与容量外推")
    parser.add_argument("--mongo-uri", default=None, help="MongoDB URI（仅用于本次进程，不输出）")
    parser.add_argument("--db-name", default=None, help="数据库名；省略时使用 URI 中数据库或 jx3bot")
    parser.add_argument("--end-time", type=int, default=int(time.time()), help="查询窗口结束 Unix 秒")
    parser.add_argument("--score-min", type=int, default=SCORE_LIMITS["score_min"], help="最小队伍平均游戏分")
    parser.add_argument("--score-max", type=int, default=SCORE_LIMITS["score_max"], help="最大队伍平均游戏分（排他）")
    parser.add_argument("--sample-size", type=int, default=1000, help="每种 active 状态的 BSON 抽样量")
    parser.add_argument("--batch-size", type=int, default=500, help="保留的正整数容量批量参数")
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _positive_int(value: Any, flag: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("--{} must be a positive integer".format(flag))
    return value


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    _positive_int(args.end_time, "end-time")
    _positive_int(args.sample_size, "sample-size")
    _positive_int(args.batch_size, "batch-size")
    score_min_bound = SCORE_LIMITS["score_min"]
    score_max_bound = SCORE_LIMITS["score_max"]
    if isinstance(args.score_min, bool) or not isinstance(args.score_min, int) or not score_min_bound <= args.score_min <= score_max_bound:
        raise ValueError("--score-min must be an integer within matchup metadata bounds")
    if isinstance(args.score_max, bool) or not isinstance(args.score_max, int) or not score_min_bound <= args.score_max <= score_max_bound:
        raise ValueError("--score-max must be an integer within matchup metadata bounds")
    if args.score_min >= args.score_max:
        raise ValueError("--score-min must be less than --score-max")
    return args


def _filters(end_time: int, days: int, team_a: Iterable[int], team_b: Iterable[int], score_min: int, score_max: int) -> Dict[str, Any]:
    return {
        "start_time": end_time - days * SECONDS_PER_DAY,
        "end_time": end_time,
        "score_min": score_min,
        "score_max": score_max,
        "team_a_kungfu_ids": list(team_a),
        "team_b_kungfu_ids": list(team_b),
        "page": 1,
        "page_size": 20,
    }


def build_cases(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Build all required query shapes without making a database call."""
    shapes = (
        ("single_kungfu", (10080,), (10242,)),
        ("double_kungfu", (10080, 10242), (10081, 10243)),
        ("full_combo", (10080, 10242, 10390), (10081, 10243, 10391)),
        ("one_side_empty", (), (10080, 10242)),
        ("both_sides_empty", (), ()),
    )
    cases = []
    for name, team_a, team_b in shapes:
        for window_days in (7, 14):
            filters = _filters(
                args.end_time, window_days, team_a, team_b, args.score_min, args.score_max
            )
            cases.append({
                "name": name,
                "window_days": window_days,
                "filters": filters,
                "filter_summary": {
                    "start_time": filters["start_time"],
                    "end_time": filters["end_time"],
                    "score_min": filters["score_min"],
                    "score_max": filters["score_max"],
                    "team_a_kungfu_ids": filters["team_a_kungfu_ids"],
                    "team_b_kungfu_ids": filters["team_b_kungfu_ids"],
                    "page": filters["page"],
                    "page_size": filters["page_size"],
                },
            })
    return cases


class _CapturedAggregateCollection:
    def __init__(self) -> None:
        self.pipeline: Optional[List[Dict[str, Any]]] = None

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> Any:
        self.pipeline = pipeline

        async def empty_cursor() -> Any:
            if False:
                yield {}
        return empty_cursor()


class _CapturedDatabase:
    def __init__(self, collection: _CapturedAggregateCollection) -> None:
        self.jjc_match_facts = collection


async def capture_search_pipeline(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Obtain the exact pipeline emitted by the production repository method."""
    collection = _CapturedAggregateCollection()
    repo = JjcMatchFactRepo(db=_CapturedDatabase(collection))
    await repo.search_matchups(filters)
    if collection.pipeline is None:
        raise RuntimeError("repository did not issue aggregate")
    return collection.pipeline


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def parse_explain(explain: Dict[str, Any]) -> Dict[str, Any]:
    """Extract stable metrics without confusing IXSCAN key direction with SORT."""
    index_names: List[str] = []
    blocking_sort = False
    facet_errors: List[str] = []
    def totals(value: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(value, dict):
            return None
        fields = ("totalKeysExamined", "totalDocsExamined", "executionTimeMillis")
        if any(isinstance(value.get(field), bool) or not isinstance(value.get(field), (int, float)) for field in fields):
            return None
        return {
            "keys_examined": value["totalKeysExamined"],
            "docs_examined": value["totalDocsExamined"],
            "execution_time_ms": value["executionTimeMillis"],
        }

    def cursor_documents(container: Any) -> List[Dict[str, Any]]:
        if not isinstance(container, dict):
            return []
        stages = container.get("stages")
        if not isinstance(stages, list):
            return []
        return [stage["$cursor"] for stage in stages if isinstance(stage, dict)
                and isinstance(stage.get("$cursor"), dict)]

    def shard_candidates(shard: Any) -> List[Dict[str, Any]]:
        if not isinstance(shard, dict):
            return []
        return [shard] + cursor_documents(shard)

    root_totals = totals(explain.get("executionStats"))
    if root_totals is not None:
        execution_metrics = root_totals
    else:
        shards = explain.get("shards")
        shard_documents = list(shards.values()) if isinstance(shards, dict) else shards
        if isinstance(shard_documents, list):
            shard_metrics = []
            for shard in shard_documents:
                metric = None
                for candidate in shard_candidates(shard):
                    metric = totals(candidate.get("executionStats"))
                    if metric is not None:
                        break
                if metric is not None:
                    shard_metrics.append(metric)
        else:
            shard_metrics = []
        if shard_metrics:
            execution_metrics = {
                "keys_examined": sum(item["keys_examined"] for item in shard_metrics),
                "docs_examined": sum(item["docs_examined"] for item in shard_metrics),
                "execution_time_ms": sum(item["execution_time_ms"] for item in shard_metrics),
            }
        else:
            pending = list(explain.values()) if isinstance(explain, dict) else []
            first_totals = None
            while pending and first_totals is None:
                level, pending = pending, []
                for item in level:
                    if isinstance(item, dict):
                        found = totals(item.get("executionStats"))
                        if found is not None:
                            first_totals = found
                            break
                        pending.extend(item.values())
                    elif isinstance(item, list):
                        pending.extend(item)
            execution_metrics = first_totals or {
                "keys_examined": 0, "docs_examined": 0, "execution_time_ms": 0,
            }
    def plan_has_sort(plan: Any) -> bool:
        for node in _walk(plan):
            if isinstance(node, dict) and node.get("stage") == "SORT":
                return True
        return False

    selected_plans: List[Any] = []

    def append_selected_plans(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        query_planner = candidate.get("queryPlanner")
        if isinstance(query_planner, dict):
            selected_plans.append(query_planner.get("winningPlan"))
        execution_stats = candidate.get("executionStats")
        if isinstance(execution_stats, dict):
            selected_plans.append(execution_stats.get("executionStages"))
        selected_plans.append(candidate.get("executionStages"))

    append_selected_plans(explain)
    for cursor in cursor_documents(explain):
        append_selected_plans(cursor)
    shards = explain.get("shards")
    shard_documents = list(shards.values()) if isinstance(shards, dict) else shards
    if isinstance(shard_documents, list):
        for shard in shard_documents:
            for candidate in shard_candidates(shard):
                append_selected_plans(candidate)
    blocking_sort = any(plan_has_sort(plan) for plan in selected_plans)

    for plan in selected_plans:
        for node in _walk(plan):
            if not isinstance(node, dict):
                continue
            index_name = node.get("indexName")
            if isinstance(index_name, str) and index_name not in index_names:
                index_names.append(index_name)

    for node in _walk(explain):
        if not isinstance(node, dict):
            continue
        execution_failure = node.get("executionFailure")
        error_message = node.get("errorMessage")
        if execution_failure and isinstance(error_message, str):
            facet_errors.append(error_message)
        elif execution_failure:
            facet_errors.append("executionFailure")
        elif isinstance(error_message, str):
            facet_errors.append(error_message)
        for nested_value in node.values():
            if isinstance(nested_value, str):
                lower = nested_value.lower()
                if "facet" in lower or "memory" in lower or "100mb" in lower:
                    facet_errors.append(nested_value)
    deduplicated_errors: List[str] = []
    for error in facet_errors:
        if error not in deduplicated_errors:
            deduplicated_errors.append(error)
    return {
        "index_names": index_names,
        "blocking_sort": blocking_sort,
        "keys_examined": execution_metrics["keys_examined"],
        "docs_examined": execution_metrics["docs_examined"],
        "execution_time_ms": execution_metrics["execution_time_ms"],
        "facet_errors": deduplicated_errors,
    }


async def collect_capacity(
    database: Any,
    sample_size: int,
    batch_size: int,
    fact_builder: Any = build_match_fact,
) -> Dict[str, Any]:
    """Estimate projected-fact capacity from read-only historical detail samples."""
    collection = database.jjc_match_detail
    source_documents = await collection.count_documents({})
    cursor = collection.aggregate([
        {"$sample": {"size": sample_size}},
        {"$project": MATCH_FACT_SOURCE_PROJECTION},
    ], batchSize=batch_size)
    active_sample: List[Dict[str, Any]] = []
    score_incomplete_active_sample: List[Dict[str, Any]] = []
    tombstone_sample: List[Dict[str, Any]] = []
    source_sample_count = 0
    invalid_match_id = 0
    build_failed = 0
    async for document in cursor:
        if not isinstance(document, dict):
            continue
        source_sample_count += 1
        match_id = normalize_positive_int(document.get("match_id"))
        if match_id is None:
            invalid_match_id += 1
            continue
        try:
            fact = fact_builder(
                match_id, match_fact_source_payload(document), MATCH_FACT_SCHEMA_VERSION,
            )
        except Exception:
            build_failed += 1
            continue
        if not isinstance(fact, dict):
            build_failed += 1
        elif fact.get("active") is True:
            active_sample.append(fact)
            team1 = fact.get("team1")
            team2 = fact.get("team2")
            if (
                not isinstance(team1, dict) or not bool(team1.get("score_complete"))
                or not isinstance(team2, dict) or not bool(team2.get("score_complete"))
            ):
                score_incomplete_active_sample.append(fact)
        elif fact.get("active") is False:
            tombstone_sample.append(fact)
        else:
            build_failed += 1

    def estimated_count(count: int) -> float:
        return source_documents * count / source_sample_count if source_sample_count else 0

    def volume(documents: List[Dict[str, Any]], estimated_documents: float, include_combos: bool) -> Dict[str, Any]:
        count = len(documents)
        bson_total = sum(len(BSON.encode(document)) for document in documents)
        average_bson = bson_total / count if count else 0
        result = {
            "sample_count": count,
            "average_bson_bytes": average_bson,
            "estimated_bson_bytes": average_bson * estimated_documents if count else 0,
        }
        if include_combos:
            combo_total = sum(
                len(document.get("any_team_combo_keys", []))
                if isinstance(document.get("any_team_combo_keys"), list) else 0
                for document in documents
            )
            average_combos = combo_total / count if count else 0
            result["average_combo_index_entries"] = average_combos
            result["estimated_combo_index_entries"] = average_combos * estimated_documents if count else 0
        return result

    active_estimated_documents = estimated_count(len(active_sample))
    score_incomplete_active_estimated_documents = estimated_count(
        len(score_incomplete_active_sample)
    )
    tombstone_estimated_documents = estimated_count(len(tombstone_sample))
    active_volume = volume(active_sample, active_estimated_documents, True)
    tombstone_volume = volume(tombstone_sample, tombstone_estimated_documents, False)
    return {
        "source_documents": source_documents,
        "source_sample_count": source_sample_count,
        "invalid_match_id": invalid_match_id,
        "build_failed": build_failed,
        "active_estimated_documents": active_estimated_documents,
        "score_incomplete_active_sample_count": len(score_incomplete_active_sample),
        "score_incomplete_active_estimated_documents": score_incomplete_active_estimated_documents,
        "tombstone_estimated_documents": tombstone_estimated_documents,
        "active_sample_count": active_volume["sample_count"],
        "active_average_bson_bytes": active_volume["average_bson_bytes"],
        "active_estimated_bson_bytes": active_volume["estimated_bson_bytes"],
        "active_average_combo_index_entries": active_volume["average_combo_index_entries"],
        "active_estimated_combo_index_entries": active_volume["estimated_combo_index_entries"],
        "tombstone_sample_count": tombstone_volume["sample_count"],
        "tombstone_average_bson_bytes": tombstone_volume["average_bson_bytes"],
        "tombstone_estimated_bson_bytes": tombstone_volume["estimated_bson_bytes"],
    }


async def collect_report(args: argparse.Namespace, database: Any) -> Dict[str, Any]:
    """Collect all explain cases and capacity estimates using read-only commands."""
    performance = []
    failed_case_count = 0
    for case in build_cases(args):
        pipeline = await capture_search_pipeline(case["filters"])
        try:
            explain = await database.command({
                "explain": {"aggregate": COLLECTION_NAME, "pipeline": pipeline, "cursor": {}},
                "verbosity": "executionStats",
            })
            metrics = parse_explain(explain if isinstance(explain, dict) else {})
        except Exception as exc:
            failed_case_count += 1
            code = getattr(exc, "code", None)
            name = getattr(exc, "name", None)
            metrics = {
                "index_names": [],
                "blocking_sort": False,
                "keys_examined": 0,
                "docs_examined": 0,
                "execution_time_ms": 0,
                "facet_errors": [{
                    "error_type": type(exc).__name__,
                    "code": code if isinstance(code, int) and not isinstance(code, bool) else None,
                    "name": name if isinstance(name, str) and name.replace("_", "").replace("-", "").isalnum() else None,
                }],
            }
        performance.append({
            "name": case["name"],
            "window_days": case["window_days"],
            "filter_summary": case["filter_summary"],
            **metrics,
        })
    return {
        "performance": performance,
        "failed_case_count": failed_case_count,
        "capacity": await collect_capacity(database, args.sample_size, args.batch_size),
    }


async def run(
    args: argparse.Namespace,
    db: Any = None,
    client_factory: Any = AsyncIOMotorClient,
) -> Dict[str, Any]:
    """Run the read-only check and reliably close a client created here."""
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
        return await collect_report(args, database)
    finally:
        if client is not None:
            client.close()


def main(argv: Optional[List[str]] = None) -> int:
    try:
        report = asyncio.run(run(parse_args(argv)))
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
