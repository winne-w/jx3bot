from __future__ import annotations

import copy
import datetime
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from pymongo import UpdateOne

from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo
from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo
from src.storage.mongo_repos.jjc_match_snapshot_repo import JjcMatchSnapshotRepo


def _make_match_payload(match_id: int = 1001) -> Dict[str, Any]:
    return {
        "cached_at": 1710000000.0,
        "data": {
            "match_id": match_id,
            "detail": {
                "team1": {
                    "won": True,
                    "players_info": [
                        {
                            "global_id": "10001",
                            "kungfu": "冰心诀",
                            "armors": [{"pos": 1, "ui_id": "a1", "name": "破军"}],
                            "talents": [{"level": 1, "id": "t1", "name": "奇穴一"}],
                        }
                    ],
                },
                "team2": {
                    "won": False,
                    "players_info": [
                        {
                            "global_id": "10002",
                            "kungfu": "云裳心经",
                        }
                    ],
                },
            },
        },
    }


class TestSaveMatchDetailSingleWrite(unittest.IsolatedAsyncioTestCase):
    async def test_single_write_compacted_true_on_snapshot_success(self) -> None:
        payload = _make_match_payload(2001)
        original = copy.deepcopy(payload)

        col = SimpleNamespace(update_one=AsyncMock())
        db = SimpleNamespace(jjc_match_detail=col)
        snapshot_repo = SimpleNamespace(
            save_equipment_snapshot=AsyncMock(),
            save_talent_snapshot=AsyncMock(),
        )
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        saved = await repo.save_match_detail(2001, payload)

        self.assertIs(saved, True)
        snapshot_repo.save_equipment_snapshot.assert_awaited_once()
        snapshot_repo.save_talent_snapshot.assert_awaited_once()
        self.assertEqual(col.update_one.await_count, 1)

        call_args = col.update_one.await_args
        self.assertEqual(call_args.args[0], {"match_id": 2001})
        self.assertIs(call_args.kwargs.get("upsert"), True)
        set_doc = call_args.args[1]["$set"]
        self.assertIs(set_doc.get("compacted"), True)
        stored_player = set_doc["data"]["detail"]["team1"]["players_info"][0]
        self.assertNotIn("armors", stored_player)
        self.assertNotIn("talents", stored_player)
        self.assertIn("equipment_snapshot_hash", stored_player)
        self.assertIn("talent_snapshot_hash", stored_player)
        self.assertEqual(payload, original)

    async def test_single_write_degraded_compacted_false_on_snapshot_failure(self) -> None:
        payload = _make_match_payload(2002)
        original = copy.deepcopy(payload)

        col = SimpleNamespace(update_one=AsyncMock())
        db = SimpleNamespace(jjc_match_detail=col)
        snapshot_repo = SimpleNamespace(
            save_equipment_snapshot=AsyncMock(side_effect=RuntimeError("snapshot write error")),
            save_talent_snapshot=AsyncMock(),
        )
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        saved = await repo.save_match_detail(2002, payload)

        self.assertIs(saved, True)
        self.assertEqual(col.update_one.await_count, 1)

        call_args = col.update_one.await_args
        self.assertEqual(call_args.args[0], {"match_id": 2002})
        self.assertIs(call_args.kwargs.get("upsert"), True)
        set_doc = call_args.args[1]["$set"]
        self.assertIs(set_doc.get("compacted"), False)
        stored_player = set_doc["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(stored_player["armors"], original["data"]["detail"]["team1"]["players_info"][0]["armors"])
        self.assertEqual(stored_player["talents"], original["data"]["detail"]["team1"]["players_info"][0]["talents"])
        self.assertEqual(payload, original)


class TestSaveRoleRecentExpiresAtDt(unittest.IsolatedAsyncioTestCase):
    async def test_writes_utc_datetime_expires_at_dt(self) -> None:
        col = SimpleNamespace(update_one=AsyncMock())
        db = SimpleNamespace(jjc_role_recent=col)
        repo = JjcInspectRepo(db=db)

        before = datetime.datetime.now(datetime.timezone.utc)
        await repo.save_role_recent("梦江南", "测试角色", {"cached_at": 1710000100.0, "data": {"ok": True}})
        after = datetime.datetime.now(datetime.timezone.utc)

        col.update_one.assert_awaited_once()
        set_doc = col.update_one.await_args.args[1]["$set"]
        self.assertEqual(set_doc["cached_at"], 1710000100.0)
        expires_at_dt = set_doc.get("expires_at_dt")
        self.assertIsInstance(expires_at_dt, datetime.datetime)
        self.assertEqual(expires_at_dt.tzinfo, datetime.timezone.utc)
        self.assertGreaterEqual(expires_at_dt, before + datetime.timedelta(seconds=86395))
        self.assertLessEqual(expires_at_dt, after + datetime.timedelta(seconds=86405))


class _FakeAggregateCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class TestParticipantRepoCasAndAggregate(unittest.IsolatedAsyncioTestCase):
    async def test_replace_rejects_stale_cached_at(self) -> None:
        col = SimpleNamespace(
            find_one=AsyncMock(return_value={"cached_at": 2000.0}),
            bulk_write=AsyncMock(),
            update_one=AsyncMock(),
            delete_many=AsyncMock(),
        )
        repo = JjcMatchParticipantRepo(db=SimpleNamespace(jjc_match_participants=col))

        written = await repo.replace_match_participants(
            3001,
            [{"global_id": "g1", "cached_at": 1500.0, "kungfu": "冰心诀"}],
        )

        self.assertEqual(written, 0)
        col.find_one.assert_awaited_once_with({"match_id": 3001}, {"cached_at": 1})
        col.bulk_write.assert_not_awaited()
        col.update_one.assert_not_awaited()
        col.delete_many.assert_not_awaited()

    async def test_replace_accepts_newer_or_equal_cached_at_and_uses_bulk_write(self) -> None:
        for incoming in (2000.0, 2500.0):
            with self.subTest(incoming=incoming):
                col = SimpleNamespace(
                    find_one=AsyncMock(return_value={"cached_at": 2000.0}),
                    bulk_write=AsyncMock(),
                    update_one=AsyncMock(),
                    delete_many=AsyncMock(),
                )
                repo = JjcMatchParticipantRepo(db=SimpleNamespace(jjc_match_participants=col))

                written = await repo.replace_match_participants(
                    3002,
                    [
                        {"global_id": "g1", "cached_at": incoming, "kungfu": "冰心诀"},
                        {"global_id": "g2", "cached_at": incoming, "kungfu": "云裳心经"},
                    ],
                )

                self.assertEqual(written, 2)
                col.bulk_write.assert_awaited_once()
                ops = col.bulk_write.await_args.args[0]
                self.assertEqual(len(ops), 2)
                self.assertTrue(all(isinstance(op, UpdateOne) for op in ops))
                col.update_one.assert_not_awaited()
                col.delete_many.assert_awaited_once_with(
                    {"match_id": 3002, "global_id": {"$nin": ["g1", "g2"]}}
                )

    async def test_replace_falls_back_to_update_one_when_bulk_write_absent(self) -> None:
        col = SimpleNamespace(
            find_one=AsyncMock(return_value=None),
            update_one=AsyncMock(),
            delete_many=AsyncMock(),
        )
        repo = JjcMatchParticipantRepo(db=SimpleNamespace(jjc_match_participants=col))

        written = await repo.replace_match_participants(
            3003,
            [{"global_id": "g1", "cached_at": 2100.0, "kungfu": "冰心诀"}],
        )

        self.assertEqual(written, 1)
        col.update_one.assert_awaited_once()
        col.delete_many.assert_awaited_once()

    async def test_aggregate_winning_kungfu_pipeline_and_results(self) -> None:
        captured_pipelines: List[List[Dict[str, Any]]] = []
        agg_docs = [
            {"_id": "冰心诀", "wins": 12, "latest_match_time": 1710000900, "latest_match_id": 9002},
            {"_id": "云裳心经", "wins": 5, "latest_match_time": 1710000500, "latest_match_id": 9001},
        ]

        def _aggregate(pipeline: List[Dict[str, Any]]) -> _FakeAggregateCursor:
            captured_pipelines.append(pipeline)
            return _FakeAggregateCursor(agg_docs)

        col = SimpleNamespace(aggregate=_aggregate)
        repo = JjcMatchParticipantRepo(db=SimpleNamespace(jjc_match_participants=col))

        results = await repo.aggregate_winning_kungfu("g100", season_start_time=1710000000, match_type=3)

        self.assertEqual(len(captured_pipelines), 1)
        pipeline = captured_pipelines[0]
        self.assertEqual(
            pipeline[0]["$match"],
            {
                "global_id": "g100",
                "match_type": 3,
                "detail_available": True,
                "won": True,
                "kungfu": {"$type": "string", "$ne": ""},
                "match_time": {"$gte": 1710000000},
            },
        )
        self.assertEqual(pipeline[1], {"$sort": {"match_time": -1, "match_id": -1}})
        self.assertEqual(
            pipeline[2],
            {
                "$group": {
                    "_id": "$kungfu",
                    "wins": {"$sum": 1},
                    "latest_match_time": {"$first": "$match_time"},
                    "latest_match_id": {"$first": "$match_id"},
                }
            },
        )
        self.assertEqual(pipeline[3], {"$sort": {"wins": -1, "latest_match_time": -1, "latest_match_id": -1}})
        self.assertEqual(
            results,
            [
                {"kungfu": "冰心诀", "wins": 12, "latest_match_time": 1710000900, "latest_match_id": 9002},
                {"kungfu": "云裳心经", "wins": 5, "latest_match_time": 1710000500, "latest_match_id": 9001},
            ],
        )


class TestSnapshotRepoFloatLastSeenAt(unittest.IsolatedAsyncioTestCase):
    async def test_equipment_and_talent_snapshots_default_last_seen_at_to_float(self) -> None:
        equip_col = MagicMock()
        equip_col.update_one = AsyncMock()
        talent_col = MagicMock()
        talent_col.update_one = AsyncMock()
        db = SimpleNamespace(jjc_equipment_snapshot=equip_col, jjc_talent_snapshot=talent_col)

        repo = JjcMatchSnapshotRepo(db=db)
        await repo.save_equipment_snapshot("eq_hash", [{"pos": 1}])
        await repo.save_talent_snapshot("tl_hash", [{"level": 1}])

        equip_last_seen = equip_col.update_one.await_args.args[1]["$set"]["last_seen_at"]
        talent_last_seen = talent_col.update_one.await_args.args[1]["$set"]["last_seen_at"]
        self.assertIsInstance(equip_last_seen, float)
        self.assertIsInstance(talent_last_seen, float)


if __name__ == "__main__":
    unittest.main()
