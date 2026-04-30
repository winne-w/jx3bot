"""
测试 scripts/migrate_jjc_match_detail_snapshots.py 迁移逻辑。

使用 fake async collections 代替真实 MongoDB。
"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# 将 scripts 加入路径以导入迁移函数
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import migrate_jjc_match_detail_snapshots as mig


# ---- Fake async MongoDB 集合 ----

class FakeAsyncCursor:
    """模拟 motor cursor。"""

    def __init__(self, docs: List[Dict[str, Any]], filter_dict: Optional[Dict[str, Any]] = None):
        self._all_docs = docs
        self._limit_val: Optional[int] = None
        self._sort_spec = None

    def limit(self, n: int) -> "FakeAsyncCursor":
        self._limit_val = n
        return self

    def sort(self, key: str, direction: int) -> "FakeAsyncCursor":
        self._sort_spec = (key, direction)
        return self

    async def to_list(self, _length: Any) -> List[Dict[str, Any]]:
        result = list(self._all_docs)
        if self._sort_spec:
            key, direction = self._sort_spec
            reverse = direction < 0
            result.sort(key=lambda d: d.get(key, 0), reverse=reverse)
        if self._limit_val is not None:
            result = result[:self._limit_val]
        # deep copy to prevent mutation of internal state
        return copy.deepcopy(result)


class FakeAsyncCollection:
    """模拟 motor AsyncIOMotorCollection（内存字典存储）。"""

    def __init__(self):
        self._docs: Dict[Any, List[Dict[str, Any]]] = {}  # _id -> doc

    def _next_id(self) -> int:
        return len(self._docs) + 1

    async def find_one(self, filter_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for doc in self._docs.values():
            if self._match(doc, filter_dict):
                return copy.deepcopy(doc)
        return None

    async def update_one(
        self,
        filter_dict: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False,
    ) -> "FakeUpdateResult":
        for oid, doc in list(self._docs.items()):
            if self._match(doc, filter_dict):
                self._apply_update(doc, update)
                return FakeUpdateResult(matched=1, modified=1, upserted_id=None)

        if upsert:
            new_doc: Dict[str, Any] = dict(filter_dict)
            self._apply_update(new_doc, update)  # type: ignore[arg-type]
            oid = self._next_id()
            new_doc["_id"] = oid
            self._docs[oid] = new_doc
            return FakeUpdateResult(matched=0, modified=0, upserted_id=oid)

        return FakeUpdateResult(matched=0, modified=0, upserted_id=None)

    async def insert_one(self, doc: Dict[str, Any]) -> "FakeInsertResult":
        oid = self._next_id()
        d = dict(doc)
        d["_id"] = oid
        self._docs[oid] = d
        return FakeInsertResult(oid)

    def find(self, filter_dict: Optional[Dict[str, Any]] = None) -> FakeAsyncCursor:
        if filter_dict:
            matching = [d for d in self._docs.values() if self._match(d, filter_dict)]
        else:
            matching = list(self._docs.values())
        return FakeAsyncCursor(matching)

    async def estimated_document_count(self) -> int:
        return len(self._docs)

    async def count_documents(self, filter_dict: Optional[Dict[str, Any]] = None) -> int:
        if filter_dict is None:
            return len(self._docs)
        return sum(1 for d in self._docs.values() if self._match(d, filter_dict))

    async def delete_many(self, filter_dict: Dict[str, Any]) -> "FakeDeleteResult":
        removed = 0
        for oid in list(self._docs.keys()):
            if self._match(self._docs[oid], filter_dict):
                del self._docs[oid]
                removed += 1
        return FakeDeleteResult(removed)

    async def drop(self) -> None:
        self._docs.clear()

    @staticmethod
    def _match(doc: Dict[str, Any], filter_dict: Dict[str, Any]) -> bool:
        for key, value in filter_dict.items():
            if isinstance(value, dict):
                # 处理 $gt 等操作符
                doc_val = doc.get(key)
                for op, op_val in value.items():
                    if op == "$gt":
                        if not (isinstance(doc_val, (int, float)) and doc_val > op_val):
                            return False
                    elif op == "$gte":
                        if not (isinstance(doc_val, (int, float)) and doc_val >= op_val):
                            return False
                    elif op == "$lt":
                        if not (isinstance(doc_val, (int, float)) and doc_val < op_val):
                            return False
                    elif op == "$ne":
                        if doc_val == op_val:
                            return False
                    else:
                        return False
            elif doc.get(key) != value:
                return False
        return True

    @staticmethod
    def _apply_update(doc: Dict[str, Any], update: Dict[str, Any]) -> None:
        set_fields = update.get("$set", {})
        for k, v in set_fields.items():
            doc[k] = v
        unset_fields = update.get("$unset", {})
        for k in unset_fields:
            doc.pop(k, None)
        set_on_insert = update.get("$setOnInsert", {})
        # 仅在插入时应用（Fake 简化：如果 doc 是新建的，_id 不存在则应用）
        if set_on_insert:
            for k, v in set_on_insert.items():
                if k not in doc:
                    doc[k] = v


class FakeUpdateResult:
    def __init__(self, matched: int, modified: int, upserted_id: Any):
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = upserted_id


class FakeInsertResult:
    def __init__(self, inserted_id: Any):
        self.inserted_id = inserted_id


class FakeDeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


class FakeAsyncDatabase:
    """模拟 motor AsyncIOMotorDatabase，按需创建 fake collection。"""

    def __init__(self):
        self._collections: Dict[str, FakeAsyncCollection] = {}

    def __getitem__(self, name: str) -> FakeAsyncCollection:
        if name not in self._collections:
            self._collections[name] = FakeAsyncCollection()
        return self._collections[name]

    def get_collection(self, name: str) -> FakeAsyncCollection:
        return self[name]


# ---- 测试数据构造 ----

def _make_armor(ui_id: str = "10001", name: str = "逐星扬威·衣", pos: int = 1) -> Dict[str, Any]:
    return {
        "ui_id": ui_id,
        "quality": "5",
        "name": name,
        "strength_evel": "6",
        "permanent_enchant": "头·攻击",
        "temporary_enchant": "",
        "mount1": "",
        "mount2": "",
        "mount3": "",
        "mount4": "",
        "pos": pos,
        "icon": "icon_{}".format(ui_id),
        "equip_box_strength_level": "6",
    }


def _make_talent(talent_id: str = "3204", name: str = "任驰骋", level: str = "1") -> Dict[str, Any]:
    return {
        "id": talent_id,
        "name": name,
        "icon": "icon_{}".format(talent_id),
        "desc": "一些描述",
        "level": level,
    }


def _make_player(
    role_name: str = "测试角色",
    armors: Optional[List[Dict[str, Any]]] = None,
    talents: Optional[List[Dict[str, Any]]] = None,
    metrics: Optional[List[Dict[str, Any]]] = None,
    body_qualities: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    player: Dict[str, Any] = {
        "role_name": role_name,
        "global_role_id": "gid_{}".format(role_name),
        "role_id": "rid_{}".format(role_name),
        "person_id": "pid_{}".format(role_name),
        "person_name": role_name,
        "person_avatar": "",
        "zone": "zone1",
        "server": "server1",
        "total_count": 100,
        "win_count": 50,
        "win_rate": 50,
        "mvp_count": 5,
        "mmr": 2000,
        "score": 1800,
        "total_score": 3600,
        "ranking": "A",
        "kungfu": "天策",
        "kungfu_id": 1,
        "mvp": False,
        "equip_score": 10000,
        "equip_strength_score": 5000,
        "stone_score": 3000,
        "max_hp": 50000,
        "odd": False,
        "fight_seconds": 300,
    }
    if armors is not None:
        player["armors"] = armors
    if talents is not None:
        player["talents"] = talents
    if metrics is not None:
        player["metrics"] = metrics
    if body_qualities is not None:
        player["body_qualities"] = body_qualities
    return player


def _make_match_detail_doc(
    match_id: int = 123456,
    team1_players: Optional[List[Dict[str, Any]]] = None,
    team2_players: Optional[List[Dict[str, Any]]] = None,
    cached_at: Optional[float] = None,
    with_snapshot_migration: bool = False,
) -> Dict[str, Any]:
    import time as _time
    data: Dict[str, Any] = {
        "match_id": match_id,
        "match_time": 1700000000,
        "query_backend": False,
        "basic_info": {"map": "青竹书院"},
        "team1": {
            "won": True,
            "team_name": "红队",
            "players_info": team1_players or [],
        },
        "team2": {
            "won": False,
            "team_name": "蓝队",
            "players_info": team2_players or [],
        },
        "videos": [],
        "hidden": False,
    }
    doc: Dict[str, Any] = {
        "match_id": match_id,
        "cached_at": cached_at if cached_at is not None else _time.time(),
        "data": data,
    }
    if with_snapshot_migration:
        doc["snapshot_migration"] = {
            "version": 1,
            "migrated_at": datetime.now(timezone.utc),
            "equipment_snapshot_count": 2,
            "talent_snapshot_count": 2,
        }
    return doc


# ---- 纯函数测试 ----

class TestSnapshotHashHelpers(unittest.TestCase):
    """测试 hash 计算辅助函数。"""

    def test_empty_armors_produces_stable_hash(self):
        h = mig.calculate_snapshot_hash([])
        self.assertIsInstance(h, str)
        self.assertEqual(64, len(h))
        # 空数组 hash 稳定
        self.assertEqual(h, mig.calculate_snapshot_hash([]))

    def test_armor_different_key_order_same_hash(self):
        a1 = [{"pos": 1, "ui_id": "10001", "name": "甲"}]
        a2 = [{"name": "甲", "pos": 1, "ui_id": "10001"}]
        self.assertEqual(
            mig.calculate_snapshot_hash(mig.normalize_equipment_snapshot(a1)),
            mig.calculate_snapshot_hash(mig.normalize_equipment_snapshot(a2)),
        )

    def test_armor_different_array_order_same_hash(self):
        a1 = [
            {"pos": 1, "ui_id": "10001", "name": "甲"},
            {"pos": 2, "ui_id": "10002", "name": "乙"},
        ]
        a2 = [
            {"pos": 2, "ui_id": "10002", "name": "乙"},
            {"pos": 1, "ui_id": "10001", "name": "甲"},
        ]
        self.assertEqual(
            mig.calculate_snapshot_hash(mig.normalize_equipment_snapshot(a1)),
            mig.calculate_snapshot_hash(mig.normalize_equipment_snapshot(a2)),
        )

    def test_different_armors_different_hash(self):
        a1 = [_make_armor(ui_id="10001", name="甲")]
        a2 = [_make_armor(ui_id="10002", name="乙")]
        self.assertNotEqual(
            mig.calculate_snapshot_hash(mig.normalize_equipment_snapshot(a1)),
            mig.calculate_snapshot_hash(mig.normalize_equipment_snapshot(a2)),
        )

    def test_talent_different_order_same_hash(self):
        t1 = [
            {"id": "3204", "level": "1", "name": "任驰骋"},
            {"id": "3205", "level": "2", "name": "破风"},
        ]
        t2 = [
            {"id": "3205", "level": "2", "name": "破风"},
            {"id": "3204", "level": "1", "name": "任驰骋"},
        ]
        self.assertEqual(
            mig.calculate_snapshot_hash(mig.normalize_talent_snapshot(t1)),
            mig.calculate_snapshot_hash(mig.normalize_talent_snapshot(t2)),
        )

    def test_input_not_mutated(self):
        armors = [_make_armor(ui_id="10001")]
        original = copy.deepcopy(armors)
        mig.normalize_equipment_snapshot(armors)
        self.assertEqual(original, armors)

        talents = [_make_talent(talent_id="3204")]
        original = copy.deepcopy(talents)
        mig.normalize_talent_snapshot(talents)
        self.assertEqual(original, talents)


class TestComputeSnapshotForPlayer(unittest.TestCase):
    """测试 _compute_snapshot_for_player。"""

    def test_player_with_armors_and_talents(self):
        player = _make_player(
            armors=[_make_armor()],
            talents=[_make_talent()],
        )
        eq_hash, ta_hash, norm_armors, norm_talents = mig._compute_snapshot_for_player(player)
        self.assertIsNotNone(eq_hash)
        self.assertIsNotNone(ta_hash)
        self.assertEqual(64, len(eq_hash))
        self.assertEqual(64, len(ta_hash))

    def test_player_without_armors(self):
        player = _make_player(talents=[_make_talent()])
        player.pop("armors", None)
        eq_hash, ta_hash, norm_armors, norm_talents = mig._compute_snapshot_for_player(player)
        self.assertIsNone(eq_hash)
        self.assertIsNotNone(ta_hash)
        self.assertIsNone(norm_armors)

    def test_player_without_talents(self):
        player = _make_player(armors=[_make_armor()])
        player.pop("talents", None)
        eq_hash, ta_hash, norm_armors, norm_talents = mig._compute_snapshot_for_player(player)
        self.assertIsNotNone(eq_hash)
        self.assertIsNone(ta_hash)
        self.assertIsNone(norm_talents)

    def test_player_with_empty_armors(self):
        player = _make_player(armors=[])
        eq_hash, ta_hash, _, _ = mig._compute_snapshot_for_player(player)
        self.assertIsNone(eq_hash)

    def test_player_with_empty_talents(self):
        player = _make_player(talents=[])
        eq_hash, ta_hash, _, _ = mig._compute_snapshot_for_player(player)
        self.assertIsNone(ta_hash)


# ---- Fake 数据库集成测试 ----

class TestDryRun(unittest.TestCase):
    """测试 dry-run 模式。"""

    def setUp(self):
        self.db = FakeAsyncDatabase()

    async def _populate(self, docs: List[Dict[str, Any]]):
        for d in docs:
            await self.db["jjc_match_detail"].insert_one(d)

    def test_dry_run_counts_matched_docs(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=[_make_armor()])],
                ),
                _make_match_detail_doc(
                    match_id=2,
                    team1_players=[_make_player(armors=[_make_armor()])],
                ),
            ])
            stats = await mig._run_dry_run(self.db)
            self.assertEqual(2, stats["matched_docs"])
            self.assertEqual(2, stats["would_migrate"])
            self.assertEqual(0, stats["already_migrated"])

        import asyncio
        asyncio.run(_test())

    def test_dry_run_no_writes_to_collections(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=[_make_armor()])],
                ),
            ])
            await mig._run_dry_run(self.db)
            self.assertEqual(0, await self.db["jjc_equipment_snapshot"].estimated_document_count())
            self.assertEqual(0, await self.db["jjc_talent_snapshot"].estimated_document_count())
            self.assertEqual(0, await self.db["jjc_match_detail_snapshot_migration_backup"].estimated_document_count())
            # jjc_match_detail 不变
            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            self.assertIsNotNone(doc)
            self.assertNotIn("snapshot_migration", doc)

        import asyncio
        asyncio.run(_test())

    def test_dry_run_skips_already_migrated(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=[_make_armor()])],
                    with_snapshot_migration=True,
                ),
                _make_match_detail_doc(
                    match_id=2,
                    team1_players=[_make_player(armors=[_make_armor()])],
                ),
            ])
            stats = await mig._run_dry_run(self.db)
            self.assertEqual(2, stats["matched_docs"])
            self.assertEqual(1, stats["already_migrated"])
            self.assertEqual(1, stats["would_migrate"])

        import asyncio
        asyncio.run(_test())

    def test_dry_run_with_limit(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(match_id=i, team1_players=[_make_player(armors=[_make_armor()])])
                for i in range(10)
            ])
            stats = await mig._run_dry_run(self.db, limit=3)
            self.assertEqual(3, stats["matched_docs"])

        import asyncio
        asyncio.run(_test())


class TestApply(unittest.TestCase):
    """测试 apply 迁移。"""

    def setUp(self):
        self.db = FakeAsyncDatabase()

    async def _populate(self, docs: List[Dict[str, Any]]):
        for d in docs:
            await self.db["jjc_match_detail"].insert_one(d)

    def test_apply_writes_snapshots(self):
        async def _test():
            armors = [_make_armor(ui_id="10001")]
            talents = [_make_talent(talent_id="3204")]
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=armors, talents=talents)],
                ),
            ])
            stats = await mig._run_apply(self.db)

            self.assertEqual(1, stats["migrated_docs"])
            self.assertEqual(0, stats["skipped_docs"])
            self.assertEqual(1, stats["backup_docs_written"])
            self.assertEqual(1, stats["equipment_snapshots_written"])
            self.assertEqual(1, stats["talent_snapshots_written"])

            # 验证 snapshot 集合
            eq_docs = await self.db["jjc_equipment_snapshot"].find().to_list(None)
            self.assertEqual(1, len(eq_docs))
            self.assertEqual(armors, eq_docs[0]["armors"])

            ta_docs = await self.db["jjc_talent_snapshot"].find().to_list(None)
            self.assertEqual(1, len(ta_docs))
            self.assertEqual(talents, ta_docs[0]["talents"])

        import asyncio
        asyncio.run(_test())

    def test_apply_removes_armors_talents_from_player(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(
                        armors=[_make_armor()],
                        talents=[_make_talent()],
                    )],
                ),
            ])
            await mig._run_apply(self.db)

            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            self.assertIsNotNone(doc)
            data = doc["data"]
            players = data["team1"]["players_info"]
            self.assertEqual(1, len(players))
            self.assertNotIn("armors", players[0])
            self.assertNotIn("talents", players[0])
            self.assertIn("equipment_snapshot_hash", players[0])
            self.assertIn("talent_snapshot_hash", players[0])

        import asyncio
        asyncio.run(_test())

    def test_apply_preserves_dynamic_fields(self):
        async def _test():
            metrics = [{"id": 1, "name": "伤害", "value": 9999, "grade": "S", "ranking": 1}]
            body_qualities = [{"name": "体魄", "value": "100"}]
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(
                        armors=[_make_armor()],
                        talents=[_make_talent()],
                        metrics=metrics,
                        body_qualities=body_qualities,
                    )],
                ),
            ])
            await mig._run_apply(self.db)

            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            player = doc["data"]["team1"]["players_info"][0]
            self.assertIn("metrics", player)
            self.assertEqual(metrics, player["metrics"])
            self.assertIn("body_qualities", player)
            self.assertEqual(body_qualities, player["body_qualities"])
            self.assertIn("kungfu", player)
            self.assertIn("mmr", player)
            self.assertIn("score", player)
            self.assertIn("max_hp", player)

        import asyncio
        asyncio.run(_test())

    def test_apply_writes_backup(self):
        async def _test():
            original_data = _make_match_detail_doc(
                match_id=1,
                team1_players=[_make_player(armors=[_make_armor()])],
                cached_at=1700000000.0,
            )
            await self._populate([original_data])
            await mig._run_apply(self.db)

            backup = await self.db["jjc_match_detail_snapshot_migration_backup"].find_one({"match_id": 1})
            self.assertIsNotNone(backup)
            self.assertEqual(original_data["data"], backup["data"])
            self.assertEqual(original_data["cached_at"], backup["cached_at"])
            self.assertIn("backup_at", backup)

        import asyncio
        asyncio.run(_test())

    def test_apply_idempotent(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=[_make_armor()])],
                ),
            ])
            stats1 = await mig._run_apply(self.db)
            self.assertEqual(1, stats1["migrated_docs"])

            stats2 = await mig._run_apply(self.db)
            self.assertEqual(0, stats2["migrated_docs"])
            self.assertEqual(1, stats2["skipped_docs"])

            # 快照不应重复写入
            eq_count = await self.db["jjc_equipment_snapshot"].estimated_document_count()
            self.assertEqual(1, eq_count)

        import asyncio
        asyncio.run(_test())

    def test_apply_idempotent_does_not_overwrite_backup(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=[_make_armor()])],
                ),
            ])
            await mig._run_apply(self.db)
            backup_count1 = await self.db["jjc_match_detail_snapshot_migration_backup"].estimated_document_count()
            self.assertEqual(1, backup_count1)

            await mig._run_apply(self.db)
            backup_count2 = await self.db["jjc_match_detail_snapshot_migration_backup"].estimated_document_count()
            self.assertEqual(1, backup_count2)

        import asyncio
        asyncio.run(_test())

    def test_player_missing_armors_skips_equipment(self):
        async def _test():
            player_no_armor = _make_player(talents=[_make_talent()])
            player_no_armor.pop("armors", None)
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[player_no_armor],
                ),
            ])
            stats = await mig._run_apply(self.db)
            self.assertEqual(1, stats["migrated_docs"])
            self.assertEqual(0, stats["equipment_snapshots_written"])
            self.assertEqual(1, stats["talent_snapshots_written"])

            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            player = doc["data"]["team1"]["players_info"][0]
            self.assertNotIn("equipment_snapshot_hash", player)
            self.assertIn("talent_snapshot_hash", player)

        import asyncio
        asyncio.run(_test())

    def test_player_missing_talents_skips_talent(self):
        async def _test():
            player_no_talent = _make_player(armors=[_make_armor()])
            player_no_talent.pop("talents", None)
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[player_no_talent],
                ),
            ])
            stats = await mig._run_apply(self.db)
            self.assertEqual(1, stats["migrated_docs"])
            self.assertEqual(1, stats["equipment_snapshots_written"])
            self.assertEqual(0, stats["talent_snapshots_written"])

            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            player = doc["data"]["team1"]["players_info"][0]
            self.assertIn("equipment_snapshot_hash", player)
            self.assertNotIn("talent_snapshot_hash", player)

        import asyncio
        asyncio.run(_test())

    def test_shared_snapshot_across_players(self):
        async def _test():
            same_armors = [_make_armor(ui_id="10001")]
            p1 = _make_player(role_name="玩家1", armors=same_armors)
            p2 = _make_player(role_name="玩家2", armors=same_armors)
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[p1, p2],
                ),
            ])
            stats = await mig._run_apply(self.db)
            # 两个玩家同一套装备，只写一次 snapshot（但统计会累加）
            self.assertEqual(1, stats["migrated_docs"])
            self.assertEqual(2, stats["equipment_snapshots_written"])

            eq_count = await self.db["jjc_equipment_snapshot"].estimated_document_count()
            self.assertEqual(1, eq_count)

        import asyncio
        asyncio.run(_test())

    def test_snapshot_migration_marker(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[
                        _make_player(armors=[_make_armor()], talents=[_make_talent()]),
                        _make_player(armors=[_make_armor()], talents=[_make_talent()]),
                    ],
                ),
            ])
            await mig._run_apply(self.db)

            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            marker = doc.get("snapshot_migration")
            self.assertIsNotNone(marker)
            self.assertEqual(1, marker["version"])
            self.assertIn("migrated_at", marker)
            self.assertEqual(2, marker["equipment_snapshot_count"])
            self.assertEqual(2, marker["talent_snapshot_count"])

        import asyncio
        asyncio.run(_test())

    def test_apply_with_match_id(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(match_id=1, team1_players=[_make_player(armors=[_make_armor()])]),
                _make_match_detail_doc(match_id=2, team1_players=[_make_player(armors=[_make_armor()])]),
            ])
            stats = await mig._run_apply(self.db, match_id=1)
            self.assertEqual(1, stats["matched_docs"])
            self.assertEqual(1, stats["migrated_docs"])

            # 第 2 个文档不变
            doc2 = await self.db["jjc_match_detail"].find_one({"match_id": 2})
            self.assertNotIn("snapshot_migration", doc2)

        import asyncio
        asyncio.run(_test())

    def test_apply_with_resume_after(self):
        async def _test():
            await self._populate([
                _make_match_detail_doc(match_id=1, team1_players=[_make_player(armors=[_make_armor()])]),
                _make_match_detail_doc(match_id=2, team1_players=[_make_player(armors=[_make_armor()])]),
                _make_match_detail_doc(match_id=3, team1_players=[_make_player(armors=[_make_armor()])]),
            ])
            stats = await mig._run_apply(self.db, resume_after=1)
            self.assertEqual(2, stats["matched_docs"])
            self.assertEqual(2, stats["migrated_docs"])

            doc1 = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            self.assertNotIn("snapshot_migration", doc1)

        import asyncio
        asyncio.run(_test())


class TestRollback(unittest.TestCase):
    """测试 rollback。"""

    def setUp(self):
        self.db = FakeAsyncDatabase()

    def test_rollback_restores_data_and_cached_at(self):
        async def _test():
            armors = [_make_armor(ui_id="10001")]
            talents = [_make_talent(talent_id="3204")]
            original_doc = _make_match_detail_doc(
                match_id=1,
                team1_players=[_make_player(armors=armors, talents=talents)],
                cached_at=1700000000.0,
            )
            await self.db["jjc_match_detail"].insert_one(original_doc)
            await mig._run_apply(self.db)

            # 确认已迁移
            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            self.assertIn("snapshot_migration", doc)

            stats = await mig._run_rollback(self.db)
            self.assertEqual(1, stats["restored"])

            # 验证恢复
            restored = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            self.assertNotIn("snapshot_migration", restored)
            self.assertEqual(original_doc["cached_at"], restored["cached_at"])
            self.assertEqual(original_doc["data"], restored["data"])

        import asyncio
        asyncio.run(_test())

    def test_rollback_with_match_id(self):
        async def _test():
            for mid in (1, 2):
                doc = _make_match_detail_doc(
                    match_id=mid,
                    team1_players=[_make_player(armors=[_make_armor()])],
                )
                await self.db["jjc_match_detail"].insert_one(doc)
            await mig._run_apply(self.db)

            stats = await mig._run_rollback(self.db, match_id=1)
            self.assertEqual(1, stats["restored"])

            doc1 = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            self.assertNotIn("snapshot_migration", doc1)
            doc2 = await self.db["jjc_match_detail"].find_one({"match_id": 2})
            self.assertIn("snapshot_migration", doc2)

        import asyncio
        asyncio.run(_test())


class TestVerify(unittest.TestCase):
    """测试 verify-only 模式。"""

    def setUp(self):
        self.db = FakeAsyncDatabase()

    def test_verify_after_apply_passes(self):
        async def _test():
            armors = [_make_armor(ui_id="10001")]
            talents = [_make_talent(talent_id="3204")]
            await self.db["jjc_match_detail"].insert_one(
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=armors, talents=talents)],
                ),
            )
            await mig._run_apply(self.db)

            stats = await mig._run_verify(self.db)
            self.assertEqual(1, stats["verified"])
            self.assertEqual(0, stats["mismatch"])
            self.assertEqual(0, stats["missing_snapshot"])

        import asyncio
        asyncio.run(_test())

    def test_verify_not_migrated(self):
        async def _test():
            await self.db["jjc_match_detail"].insert_one(
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=[_make_armor()])],
                ),
            )
            stats = await mig._run_verify(self.db)
            self.assertEqual(1, stats["not_migrated"])

        import asyncio
        asyncio.run(_test())

    def test_verify_detects_missing_snapshot(self):
        async def _test():
            armors = [_make_armor(ui_id="10001")]
            await self.db["jjc_match_detail"].insert_one(
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[_make_player(armors=armors)],
                ),
            )
            await mig._run_apply(self.db)

            # 手动删除 snapshot 来模拟缺失
            await self.db["jjc_equipment_snapshot"].drop()

            stats = await mig._run_verify(self.db)
            self.assertEqual(0, stats["verified"])
            self.assertGreater(stats["missing_snapshot"], 0)

        import asyncio
        asyncio.run(_test())


class TestDropBackup(unittest.TestCase):
    """测试 drop-backup。"""

    def setUp(self):
        self.db = FakeAsyncDatabase()

    def test_drop_backup_clears_collection(self):
        async def _test():
            await self.db["jjc_match_detail_snapshot_migration_backup"].insert_one({
                "match_id": 1, "data": {}, "cached_at": 0, "backup_at": datetime.now(timezone.utc),
            })
            self.assertEqual(1, await self.db["jjc_match_detail_snapshot_migration_backup"].estimated_document_count())

            stats = await mig._run_drop_backup(self.db)
            self.assertEqual(1, stats["dropped_docs"])
            self.assertEqual(0, await self.db["jjc_match_detail_snapshot_migration_backup"].estimated_document_count())

        import asyncio
        asyncio.run(_test())


class TestIntegration(unittest.TestCase):
    """端到端流程测试。"""

    def setUp(self):
        self.db = FakeAsyncDatabase()

    def test_full_apply_then_rollback_roundtrip(self):
        async def _test():
            armors = [_make_armor(ui_id="10001"), _make_armor(ui_id="10002", pos=2)]
            talents = [_make_talent(talent_id="3204"), _make_talent(talent_id="3205", level="2")]
            metrics = [{"id": 1, "name": "伤害", "value": 9999, "grade": "S", "ranking": 1}]
            original = _make_match_detail_doc(
                match_id=1,
                team1_players=[
                    _make_player(role_name="玩家1", armors=armors, talents=talents, metrics=metrics),
                    _make_player(role_name="玩家2", armors=[_make_armor(ui_id="10003")]),
                ],
                cached_at=1700000000.0,
            )
            await self.db["jjc_match_detail"].insert_one(original)

            # 1. Apply
            stats = await mig._run_apply(self.db)
            self.assertEqual(1, stats["migrated_docs"])

            # 2. Verify
            vstats = await mig._run_verify(self.db)
            self.assertEqual(1, vstats["verified"])
            self.assertEqual(0, vstats["mismatch"])
            self.assertEqual(0, vstats["missing_snapshot"])

            # 3. Rollback
            rstats = await mig._run_rollback(self.db)
            self.assertEqual(1, rstats["restored"])

            # 4. 对比原始
            restored = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            self.assertEqual(original["cached_at"], restored["cached_at"])
            self.assertEqual(original["data"], restored["data"])
            self.assertNotIn("snapshot_migration", restored)

        import asyncio
        asyncio.run(_test())

    def test_team1_and_team2_both_processed(self):
        async def _test():
            await self.db["jjc_match_detail"].insert_one(
                _make_match_detail_doc(
                    match_id=1,
                    team1_players=[
                        _make_player(role_name="红1", armors=[_make_armor(ui_id="10001")]),
                        _make_player(role_name="红2", armors=[_make_armor(ui_id="10002")]),
                        _make_player(role_name="红3", armors=[_make_armor(ui_id="10003")]),
                    ],
                    team2_players=[
                        _make_player(role_name="蓝1", armors=[_make_armor(ui_id="10004")]),
                        _make_player(role_name="蓝2", armors=[_make_armor(ui_id="10005")]),
                        _make_player(role_name="蓝3", armors=[_make_armor(ui_id="10006")]),
                    ],
                ),
            )
            stats = await mig._run_apply(self.db)
            self.assertEqual(1, stats["migrated_docs"])
            self.assertEqual(6, stats["players_seen"])
            self.assertEqual(6, stats["equipment_snapshots_written"])

            doc = await self.db["jjc_match_detail"].find_one({"match_id": 1})
            for team_key in ("team1", "team2"):
                for player in doc["data"][team_key]["players_info"]:
                    self.assertIn("equipment_snapshot_hash", player)
                    self.assertNotIn("armors", player)

        import asyncio
        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
