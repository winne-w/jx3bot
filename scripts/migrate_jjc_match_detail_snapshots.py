"""
迁移 jjc_match_detail 中玩家 armors/talents 到 snapshot 集合。

默认 dry-run 模式，只统计不写库。

用法:
  python scripts/migrate_jjc_match_detail_snapshots.py --dry-run --limit 10
  python scripts/migrate_jjc_match_detail_snapshots.py --apply --limit 20
  python scripts/migrate_jjc_match_detail_snapshots.py --apply --match-id 123456
  python scripts/migrate_jjc_match_detail_snapshots.py --rollback --match-id 123456
  python scripts/migrate_jjc_match_detail_snapshots.py --verify-only --limit 10
  python scripts/migrate_jjc_match_detail_snapshots.py --drop-backup
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

# ---- snapshot helpers ----
# 尝试从 service / repo 层导入，若对应阶段尚未实现则使用内联实现。

try:
    from src.services.jx3.match_detail_snapshots import (
        calculate_snapshot_hash,
        normalize_equipment_snapshot,
        normalize_talent_snapshot,
    )
except ImportError:
    def _normalize_and_hash(items: List[Dict[str, Any]], sort_keys: List[str]) -> str:
        """规范化数组并计算 sha256 十六进制 hash。"""
        def _sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
            return tuple(item.get(k) for k in sort_keys)

        normalized = sorted(items, key=_sort_key)
        canonical = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def normalize_equipment_snapshot(armors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sort_keys = ["pos", "ui_id", "name"]
        return sorted(armors, key=lambda item: tuple(item.get(k) for k in sort_keys))

    def normalize_talent_snapshot(talents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sort_keys = ["level", "id", "name"]
        return sorted(talents, key=lambda item: tuple(item.get(k) for k in sort_keys))

    def calculate_snapshot_hash(items: List[Dict[str, Any]]) -> str:
        if not items:
            return hashlib.sha256(b"[]").hexdigest()
        canonical = json.dumps(
            items, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


SCHEMA_VERSION = 1
BACKUP_COLLECTION = "jjc_match_detail_snapshot_migration_backup"
EQUIPMENT_COLLECTION = "jjc_equipment_snapshot"
TALENT_COLLECTION = "jjc_talent_snapshot"
SOURCE_COLLECTION = "jjc_match_detail"


def _get_mongo_uri() -> str:
    """读取 MONGO_URI：优先环境变量，其次 runtime_config.json。"""
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

    raise RuntimeError(
        "无法获取 MONGO_URI：环境变量 MONGO_URI 和 runtime_config.json 均未配置"
    )


def _compute_snapshot_for_player(
    player: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str], Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]]:
    """计算单个玩家的装备/奇穴 snapshot hash，返回 (equip_hash, talent_hash, norm_armors, norm_talents)。"""
    equip_hash = None
    talent_hash = None
    norm_armors = None
    norm_talents = None

    armors = player.get("armors")
    if isinstance(armors, list) and armors:
        norm_armors = normalize_equipment_snapshot(armors)
        equip_hash = calculate_snapshot_hash(norm_armors)

    talents = player.get("talents")
    if isinstance(talents, list) and talents:
        norm_talents = normalize_talent_snapshot(talents)
        talent_hash = calculate_snapshot_hash(norm_talents)

    return equip_hash, talent_hash, norm_armors, norm_talents


async def _ensure_backup(
    db: AsyncIOMotorDatabase,
    match_id: int,
    data: Dict[str, Any],
    cached_at: Any,
    now: datetime,
) -> bool:
    """将原始 data/cached_at 写入备份集合（已存在则跳过），返回是否为新写入。"""
    existing = await db[BACKUP_COLLECTION].find_one({"match_id": match_id})
    if existing is not None:
        return False

    await db[BACKUP_COLLECTION].insert_one({
        "match_id": match_id,
        "data": data,
        "cached_at": cached_at,
        "backup_at": now,
    })
    return True


async def _save_equipment_snapshot(
    db: AsyncIOMotorDatabase,
    snapshot_hash: str,
    armors: List[Dict[str, Any]],
    now: datetime,
) -> None:
    """保存装备快照（按 hash 幂等 upsert）。"""
    await db[EQUIPMENT_COLLECTION].update_one(
        {"snapshot_hash": snapshot_hash},
        {
            "$setOnInsert": {
                "snapshot_hash": snapshot_hash,
                "armors": armors,
                "created_at": now,
                "schema_version": SCHEMA_VERSION,
            },
            "$set": {"last_seen_at": now},
        },
        upsert=True,
    )


async def _save_talent_snapshot(
    db: AsyncIOMotorDatabase,
    snapshot_hash: str,
    talents: List[Dict[str, Any]],
    now: datetime,
) -> None:
    """保存奇穴快照（按 hash 幂等 upsert）。"""
    await db[TALENT_COLLECTION].update_one(
        {"snapshot_hash": snapshot_hash},
        {
            "$setOnInsert": {
                "snapshot_hash": snapshot_hash,
                "talents": talents,
                "created_at": now,
                "schema_version": SCHEMA_VERSION,
            },
            "$set": {"last_seen_at": now},
        },
        upsert=True,
    )


def _estimate_bson_size(doc: Dict[str, Any]) -> int:
    """粗略估算文档 BSON 字节数（用于对比统计）。"""
    try:
        from bson import BSON
        return len(BSON.encode(doc))
    except ImportError:
        return len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))


async def _run_dry_run(
    db: AsyncIOMotorDatabase,
    limit: Optional[int] = None,
    match_id: Optional[int] = None,
    batch_size: int = 100,
    resume_after: Optional[int] = None,
) -> Dict[str, Any]:
    """统计模式，只遍历不写入。"""
    stats: Dict[str, Any] = {
        "matched_docs": 0,
        "would_migrate": 0,
        "already_migrated": 0,
        "players_seen": 0,
        "equipment_snapshots_would_write": 0,
        "talent_snapshots_would_write": 0,
        "estimated_original_bson_bytes": 0,
        "estimated_new_bson_bytes": 0,
        "estimated_saved_bson_bytes": 0,
    }

    seen_equip_hashes: set = set()
    seen_talent_hashes: set = set()

    query: Dict[str, Any] = {}
    if match_id is not None:
        query["match_id"] = match_id
    if resume_after is not None:
        query["match_id"] = {"$gt": resume_after}

    cursor = db[SOURCE_COLLECTION].find(query).sort("match_id", 1)
    if limit is not None:
        cursor = cursor.limit(limit)

    docs = await cursor.to_list(None)
    stats["matched_docs"] = len(docs)

    for doc in docs:
        mid = doc.get("match_id")
        if doc.get("snapshot_migration"):
            stats["already_migrated"] += 1
            continue

        stats["would_migrate"] += 1
        original_size = _estimate_bson_size(doc)
        stats["estimated_original_bson_bytes"] += original_size

        data = doc.get("data")
        if not isinstance(data, dict):
            continue

        new_data = dict(data)
        eq_count = 0
        ta_count = 0

        for team_key in ("team1", "team2"):
            team = new_data.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info")
            if not isinstance(players, list):
                continue

            for player in players:
                if not isinstance(player, dict):
                    continue
                stats["players_seen"] += 1

                eq_hash, ta_hash, _, _ = _compute_snapshot_for_player(player)
                if eq_hash:
                    eq_count += 1
                    if eq_hash not in seen_equip_hashes:
                        stats["equipment_snapshots_would_write"] += 1
                        seen_equip_hashes.add(eq_hash)
                if ta_hash:
                    ta_count += 1
                    if ta_hash not in seen_talent_hashes:
                        stats["talent_snapshots_would_write"] += 1
                        seen_talent_hashes.add(ta_hash)

        # 估算新大小：移除 armors/talents 后的 data + migration marker
        for team_key in ("team1", "team2"):
            team = new_data.get(team_key)
            if isinstance(team, dict):
                players = team.get("players_info")
                if isinstance(players, list):
                    for player in players:
                        if isinstance(player, dict):
                            player.pop("armors", None)
                            player.pop("talents", None)

        # 用 key 很小的 marker + hash 字符串估算
        migration_marker = {
            "version": 1,
            "equipment_snapshot_count": eq_count,
            "talent_snapshot_count": ta_count,
        }
        estimated_doc = {
            "match_id": mid,
            "cached_at": doc.get("cached_at"),
            "data": new_data,
            "snapshot_migration": migration_marker,
        }
        new_size = _estimate_bson_size(estimated_doc)
        stats["estimated_new_bson_bytes"] += new_size
        stats["estimated_saved_bson_bytes"] += max(0, original_size - new_size)

    return stats


async def _run_apply(
    db: AsyncIOMotorDatabase,
    limit: Optional[int] = None,
    match_id: Optional[int] = None,
    batch_size: int = 100,
    resume_after: Optional[int] = None,
) -> Dict[str, Any]:
    """执行迁移写入。"""
    stats: Dict[str, Any] = {
        "matched_docs": 0,
        "migrated_docs": 0,
        "skipped_docs": 0,
        "players_seen": 0,
        "equipment_snapshots_written": 0,
        "talent_snapshots_written": 0,
        "backup_docs_written": 0,
        "failed_docs": 0,
        "estimated_original_bson_bytes": 0,
        "estimated_new_bson_bytes": 0,
        "estimated_saved_bson_bytes": 0,
    }

    now_utc = datetime.now(timezone.utc)

    query: Dict[str, Any] = {}
    if match_id is not None:
        query["match_id"] = match_id
    if resume_after is not None:
        query["match_id"] = {"$gt": resume_after}

    cursor = db[SOURCE_COLLECTION].find(query).sort("match_id", 1)
    if limit is not None:
        cursor = cursor.limit(limit)

    docs = await cursor.to_list(None)
    stats["matched_docs"] = len(docs)

    for idx, doc in enumerate(docs):
        mid = doc.get("match_id")

        # 已迁移则跳过
        if doc.get("snapshot_migration"):
            stats["skipped_docs"] += 1
            continue

        original_size = _estimate_bson_size(doc)
        stats["estimated_original_bson_bytes"] += original_size

        data = doc.get("data")
        if not isinstance(data, dict):
            stats["skipped_docs"] += 1
            continue

        new_data = {}
        for k, v in data.items():
            if k in ("team1", "team2"):
                team = dict(v) if isinstance(v, dict) else v
                if isinstance(team, dict):
                    players = team.get("players_info")
                    if isinstance(players, list):
                        new_players = []
                        for player in players:
                            if not isinstance(player, dict):
                                new_players.append(player)
                                continue
                            stats["players_seen"] += 1
                            new_player = dict(player)

                            eq_hash, ta_hash, norm_armors, norm_talents = (
                                _compute_snapshot_for_player(new_player)
                            )
                            if eq_hash:
                                try:
                                    await _save_equipment_snapshot(db, eq_hash, norm_armors, now_utc)
                                    stats["equipment_snapshots_written"] += 1
                                except Exception:
                                    stats["failed_docs"] += 1
                                    raise
                                new_player["equipment_snapshot_hash"] = eq_hash
                                new_player.pop("armors", None)
                            if ta_hash:
                                try:
                                    await _save_talent_snapshot(db, ta_hash, norm_talents, now_utc)
                                    stats["talent_snapshots_written"] += 1
                                except Exception:
                                    stats["failed_docs"] += 1
                                    raise
                                new_player["talent_snapshot_hash"] = ta_hash
                                new_player.pop("talents", None)

                            new_players.append(new_player)
                        team["players_info"] = new_players
                new_data[k] = team
            else:
                new_data[k] = v

        eq_count = sum(
            1 for t in ("team1", "team2")
            for p in (
                (new_data.get(t) or {}).get("players_info") if isinstance(new_data.get(t), dict) else []
            )
            if isinstance(p, dict) and "equipment_snapshot_hash" in p
        )
        ta_count = sum(
            1 for t in ("team1", "team2")
            for p in (
                (new_data.get(t) or {}).get("players_info") if isinstance(new_data.get(t), dict) else []
            )
            if isinstance(p, dict) and "talent_snapshot_hash" in p
        )

        migration_marker = {
            "version": 1,
            "migrated_at": now_utc,
            "equipment_snapshot_count": eq_count,
            "talent_snapshot_count": ta_count,
        }

        # 备份原始数据
        backuped = await _ensure_backup(db, mid, data, doc.get("cached_at"), now_utc)
        if backuped:
            stats["backup_docs_written"] += 1

        # 更新文档
        await db[SOURCE_COLLECTION].update_one(
            {"match_id": mid},
            {
                "$set": {
                    "data": new_data,
                    "snapshot_migration": migration_marker,
                },
            },
        )

        new_size = _estimate_bson_size({
            "match_id": mid,
            "cached_at": doc.get("cached_at"),
            "data": new_data,
            "snapshot_migration": migration_marker,
        })
        stats["estimated_new_bson_bytes"] += new_size
        stats["estimated_saved_bson_bytes"] += max(0, original_size - new_size)
        stats["migrated_docs"] += 1

        if (idx + 1) % batch_size == 0:
            print(
                "进度: {}/{} migrated={} skipped={} failed={}".format(
                    idx + 1, stats["matched_docs"],
                    stats["migrated_docs"], stats["skipped_docs"], stats["failed_docs"],
                )
            )

    return stats


async def _run_rollback(
    db: AsyncIOMotorDatabase,
    limit: Optional[int] = None,
    match_id: Optional[int] = None,
) -> Dict[str, int]:
    """从备份集合恢复 data/cached_at 到 jjc_match_detail。"""
    stats = {"restored": 0, "skipped": 0, "failed": 0}

    query: Dict[str, Any] = {}
    if match_id is not None:
        query["match_id"] = match_id

    cursor = db[BACKUP_COLLECTION].find(query).sort("match_id", 1)
    if limit is not None:
        cursor = cursor.limit(limit)

    backups = await cursor.to_list(None)
    for backup in backups:
        mid = backup["match_id"]
        try:
            update_fields: Dict[str, Any] = {"data": backup["data"]}
            if "cached_at" in backup:
                update_fields["cached_at"] = backup["cached_at"]

            await db[SOURCE_COLLECTION].update_one(
                {"match_id": mid},
                {
                    "$set": update_fields,
                    "$unset": {"snapshot_migration": ""},
                },
            )
            stats["restored"] += 1
        except Exception:
            stats["failed"] += 1
            print("恢复失败: match_id={}".format(mid))

    return stats


async def _run_verify(
    db: AsyncIOMotorDatabase,
    limit: Optional[int] = None,
    match_id: Optional[int] = None,
) -> Dict[str, int]:
    """校验迁移结果：检查 snapshot 引用是否存在且 hash 匹配。"""
    stats = {"verified": 0, "mismatch": 0, "missing_snapshot": 0, "not_migrated": 0}

    query: Dict[str, Any] = {}
    if match_id is not None:
        query["match_id"] = match_id

    cursor = db[SOURCE_COLLECTION].find(query).sort("match_id", 1)
    if limit is not None:
        cursor = cursor.limit(limit)

    docs = await cursor.to_list(None)
    for doc in docs:
        mid = doc.get("match_id")
        if not doc.get("snapshot_migration"):
            stats["not_migrated"] += 1
            continue

        data = doc.get("data")
        if not isinstance(data, dict):
            continue

        ok = True
        for team_key in ("team1", "team2"):
            team = data.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info")
            if not isinstance(players, list):
                continue

            for player in players:
                if not isinstance(player, dict):
                    continue

                eq_hash = player.get("equipment_snapshot_hash")
                if eq_hash:
                    snap = await db[EQUIPMENT_COLLECTION].find_one({"snapshot_hash": eq_hash})
                    if snap is None:
                        ok = False
                        stats["missing_snapshot"] += 1
                        print(
                            "缺失装备快照: match_id={} hash={}".format(mid, eq_hash)
                        )
                    else:
                        norm_armors = normalize_equipment_snapshot(snap.get("armors") or [])
                        expected_hash = calculate_snapshot_hash(norm_armors)
                        if expected_hash != eq_hash:
                            ok = False
                            stats["mismatch"] += 1
                            print(
                                "装备 hash 不匹配: match_id={} stored={} computed={}".format(
                                    mid, eq_hash, expected_hash,
                                )
                            )

                ta_hash = player.get("talent_snapshot_hash")
                if ta_hash:
                    snap = await db[TALENT_COLLECTION].find_one({"snapshot_hash": ta_hash})
                    if snap is None:
                        ok = False
                        stats["missing_snapshot"] += 1
                        print(
                            "缺失奇穴快照: match_id={} hash={}".format(mid, ta_hash)
                        )
                    else:
                        norm_talents = normalize_talent_snapshot(snap.get("talents") or [])
                        expected_hash = calculate_snapshot_hash(norm_talents)
                        if expected_hash != ta_hash:
                            ok = False
                            stats["mismatch"] += 1
                            print(
                                "奇穴 hash 不匹配: match_id={} stored={} computed={}".format(
                                    mid, ta_hash, expected_hash,
                                )
                            )

                # 检查玩家不应再有 armors/talents 数组
                if "armors" in player:
                    ok = False
                    stats["mismatch"] += 1
                    print("残留 armors 字段: match_id={}".format(mid))
                if "talents" in player:
                    ok = False
                    stats["mismatch"] += 1
                    print("残留 talents 字段: match_id={}".format(mid))

        if ok:
            stats["verified"] += 1

    return stats


async def _run_drop_backup(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """删除备份集合。"""
    count = await db[BACKUP_COLLECTION].estimated_document_count()
    await db[BACKUP_COLLECTION].drop()
    return {"dropped_docs": count}


def _print_stats(stats: Dict[str, Any], mode: str) -> None:
    """格式化输出统计信息。"""
    print()
    print("=" * 60)
    print("迁移统计 ({})".format(mode))
    print("=" * 60)
    for key, value in stats.items():
        if isinstance(value, float):
            print("  {}: {:.1f}".format(key, value))
        else:
            print("  {}: {}".format(key, value))


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="迁移 jjc_match_detail 中玩家 armors/talents 到 snapshot 集合"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="默认模式，只统计不写库",
    )
    parser.add_argument("--apply", action="store_true", help="执行迁移")
    parser.add_argument("--rollback", action="store_true", help="从备份集合恢复")
    parser.add_argument("--verify-only", action="store_true", help="只校验迁移结果")
    parser.add_argument("--drop-backup", action="store_true", help="删除备份集合")
    parser.add_argument("--limit", type=int, default=None, help="限制处理文档数")
    parser.add_argument("--match-id", type=int, default=None, help="只处理单局")
    parser.add_argument("--batch-size", type=int, default=100, help="批处理大小")
    parser.add_argument("--resume-after", type=int, default=None, help="从某个 match_id 之后继续")
    args = parser.parse_args()

    # --apply / --rollback / --verify-only / --drop-backup 会覆盖默认 dry-run
    if args.apply or args.rollback or args.verify_only or args.drop_backup:
        args.dry_run = False

    try:
        uri = _get_mongo_uri()
    except RuntimeError as exc:
        print("错误: {}".format(exc))
        sys.exit(1)

    db_name = uri.rsplit("/", 1)[-1].split("?")[0]
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        uri, maxPoolSize=10, serverSelectionTimeoutMS=5000,
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:
        print("MongoDB 连接失败: {}".format(exc))
        sys.exit(1)

    db = client[db_name]
    print("MongoDB 连接成功: {}".format(db_name))

    source_count = await db[SOURCE_COLLECTION].estimated_document_count()
    backup_count = await db[BACKUP_COLLECTION].estimated_document_count()
    print("{} 现有文档数: {}".format(SOURCE_COLLECTION, source_count))
    print("{} 现有文档数: {}".format(BACKUP_COLLECTION, backup_count))
    print()

    if args.drop_backup:
        print("模式: DROP-BACKUP (删除备份集合)")
        stats = await _run_drop_backup(db)
        _print_stats(stats, "DROP-BACKUP")
        client.close()
        return

    if args.apply:
        print("模式: APPLY (实际写入)")
        stats = await _run_apply(
            db,
            limit=args.limit,
            match_id=args.match_id,
            batch_size=args.batch_size,
            resume_after=args.resume_after,
        )
        _print_stats(stats, "APPLY")
    elif args.rollback:
        print("模式: ROLLBACK (从备份恢复)")
        stats = await _run_rollback(
            db,
            limit=args.limit,
            match_id=args.match_id,
        )
        _print_stats(stats, "ROLLBACK")
    elif args.verify_only:
        print("模式: VERIFY-ONLY (校验迁移结果)")
        stats = await _run_verify(
            db,
            limit=args.limit,
            match_id=args.match_id,
        )
        _print_stats(stats, "VERIFY-ONLY")
    else:
        print("模式: DRY-RUN (不写入)")
        if args.limit:
            print("限制: {} 条".format(args.limit))
        if args.match_id:
            print("单局: {}".format(args.match_id))
        stats = await _run_dry_run(
            db,
            limit=args.limit,
            match_id=args.match_id,
            batch_size=args.batch_size,
            resume_after=args.resume_after,
        )
        _print_stats(stats, "DRY-RUN")
        print()
        print(">>> DRY-RUN 模式，未实际写入。使用 --apply 参数执行实际写入 <<<")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
