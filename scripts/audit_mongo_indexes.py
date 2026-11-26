#!/usr/bin/env python3
"""只读巡检 MongoDB 索引使用率、装备读索引就绪状态与时间字段 BSON 类型分布。

示例：
    python3 scripts/audit_mongo_indexes.py
    python3 scripts/audit_mongo_indexes.py --mongo-uri mongodb://127.0.0.1:27017/jx3bot --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._common.mongo import open_async_client, resolve_db_name, resolve_mongo_uri
from src.infra.mongo import verify_equipment_read_indexes

LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES: Tuple[str, ...] = (
    "idx_detail_team1_server_role_name",
    "idx_detail_team2_server_role_name",
    "idx_detail_team1_player_global_id",
    "idx_detail_team2_player_global_id",
    "idx_replay_player_role_id",
    "idx_replay_player_global_role_id",
)

TIME_TYPE_AUDIT_TARGETS: Tuple[Tuple[str, str], ...] = (
    ("jjc_equipment_snapshot", "last_seen_at"),
    ("jjc_talent_snapshot", "last_seen_at"),
    ("jjc_peak_score_rankings", "updated_at"),
)

_IGNORED_BSON_TYPES = frozenset({"missing", "null"})


def _extract_ops(entry: Mapping[str, Any]) -> int:
    accesses = entry.get("accesses")
    if isinstance(accesses, Mapping) and "ops" in accesses:
        raw_ops = accesses.get("ops")
    else:
        raw_ops = entry.get("ops", 0)
    try:
        return int(raw_ops or 0)
    except (TypeError, ValueError):
        return 0


def summarize_index_audit(
    index_stats: Iterable[Mapping[str, Any]],
    equipment_check: Mapping[str, Any],
    type_counts: Mapping[str, Mapping[str, int]],
) -> Dict[str, Any]:
    """汇总索引命中率、装备读索引状态与时间字段 BSON 类型分布（纯函数，可离线测试）。"""
    ops_by_name: Dict[str, int] = {}
    for entry in index_stats:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        ops_by_name[name] = ops_by_name.get(name, 0) + _extract_ops(entry)

    sorted_ops = {name: ops_by_name[name] for name in sorted(ops_by_name)}
    zero_ops_indexes = [
        name for name, ops in sorted_ops.items() if name != "_id_" and ops == 0
    ]
    zero_ops_legacy_multikey_indexes = [
        name
        for name in LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES
        if name in sorted_ops and sorted_ops[name] == 0
    ]

    normalized_equipment_check = {
        "ready": bool(equipment_check.get("ready", False)),
        "missing": list(equipment_check.get("missing") or []),
        "mismatched": list(equipment_check.get("mismatched") or []),
    }

    time_field_types: Dict[str, Dict[str, Any]] = {}
    mixed_time_fields: List[str] = []
    for target_key in sorted(type_counts):
        raw_counts = type_counts.get(target_key) or {}
        counts = {
            str(bson_type): int(count)
            for bson_type, count in sorted(raw_counts.items())
            if int(count) > 0
        }
        present_types = sorted(
            bson_type
            for bson_type, count in counts.items()
            if count > 0 and bson_type not in _IGNORED_BSON_TYPES
        )
        has_mixed_types = len(present_types) > 1
        if has_mixed_types:
            mixed_time_fields.append(target_key)
        time_field_types[target_key] = {
            "counts": counts,
            "present_types": present_types,
            "has_mixed_types": has_mixed_types,
        }

    return {
        "match_detail_index_ops": sorted_ops,
        "zero_ops_indexes": zero_ops_indexes,
        "zero_ops_legacy_multikey_indexes": zero_ops_legacy_multikey_indexes,
        "equipment_read_indexes": normalized_equipment_check,
        "time_field_types": time_field_types,
        "mixed_time_fields": mixed_time_fields,
    }


async def _collect_async_cursor(cursor: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    async for doc in cursor:
        rows.append(doc)
    return rows


async def run_audit(db: Any) -> Dict[str, Any]:
    """只读执行 MongoDB 索引与时间类型巡检，不修改任何集合或索引。"""
    index_stats_cursor = db["jjc_match_detail"].aggregate([{"$indexStats": {}}])
    index_stats = await _collect_async_cursor(index_stats_cursor)

    equipment_check = await verify_equipment_read_indexes(db)

    type_counts: Dict[str, Dict[str, int]] = {}
    for collection_name, field_name in TIME_TYPE_AUDIT_TARGETS:
        target_key = "{}.{}".format(collection_name, field_name)
        pipeline = [
            {
                "$group": {
                    "_id": {"$type": "${}".format(field_name)},
                    "count": {"$sum": 1},
                }
            }
        ]
        cursor = db[collection_name].aggregate(pipeline)
        rows = await _collect_async_cursor(cursor)
        counts: Dict[str, int] = {}
        for row in rows:
            bson_type = str(row.get("_id") or "missing")
            counts[bson_type] = int(row.get("count") or 0)
        type_counts[target_key] = counts

    return summarize_index_audit(index_stats, equipment_check, type_counts)


def _format_report(summary: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=== jjc_match_detail $indexStats ===")
    ops_map = summary.get("match_detail_index_ops") or {}
    if not ops_map:
        lines.append("  (无索引统计数据)")
    else:
        for name, ops in ops_map.items():
            marker = (
                " [0-ops legacy multikey]"
                if name in (summary.get("zero_ops_legacy_multikey_indexes") or [])
                else ""
            )
            lines.append("  - {}: {} ops{}".format(name, ops, marker))

    lines.append("")
    lines.append("=== equipment read indexes (v1) ===")
    equip = summary.get("equipment_read_indexes") or {}
    lines.append("  ready: {}".format(bool(equip.get("ready", False))))
    lines.append("  missing: {}".format(equip.get("missing") or []))
    lines.append("  mismatched: {}".format(equip.get("mismatched") or []))

    lines.append("")
    lines.append("=== time field BSON $type distribution ===")
    time_types = summary.get("time_field_types") or {}
    for target_key, detail in time_types.items():
        flag = " [MIXED]" if detail.get("has_mixed_types") else ""
        lines.append("  - {}: {}{}".format(target_key, detail.get("counts") or {}, flag))

    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读巡检 MongoDB 索引使用率、装备读索引状态与时间字段 BSON 类型分布",
    )
    parser.add_argument(
        "--mongo-uri",
        default=None,
        help="显式指定 MongoDB URI（默认读取 MONGO_URI 环境变量或 config.MONGO_URI）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出巡检结果",
    )
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    uri = resolve_mongo_uri(args.mongo_uri)
    db_name = resolve_db_name(uri)
    client = open_async_client(uri)
    try:
        db = client[db_name]
        summary = await run_audit(db)
    finally:
        client.close()

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(_format_report(summary))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
