from __future__ import annotations

import unittest
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo


def _make_db() -> MagicMock:
    db = MagicMock()
    db.jjc_match_detail.update_one = AsyncMock()
    return db


def _make_snapshot_repo() -> MagicMock:
    snapshot_repo = MagicMock()
    snapshot_repo.save_equipment_snapshot = AsyncMock()
    snapshot_repo.save_talent_snapshot = AsyncMock()
    return snapshot_repo


def _payload(match_id: int = 101) -> Dict[str, Any]:
    return {
        "cached_at": 1234567890.0,
        "data": {
            "match_id": match_id,
            "detail": {
                "team1": {
                    "players_info": [
                        {
                            "armors": [{"pos": 1, "name": "破军"}],
                            "talents": [{"level": 1, "name": "奇穴一"}],
                        },
                    ],
                },
            },
        },
    }


class TestSaveMatchDetailContract(unittest.IsolatedAsyncioTestCase):
    async def test_main_write_failure_propagates_and_skips_snapshot_derivation(self):
        db = _make_db()
        original_error = RuntimeError("mongo unavailable")
        db.jjc_match_detail.update_one.side_effect = original_error
        snapshot_repo = _make_snapshot_repo()
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        with self.assertRaisesRegex(RuntimeError, "mongo unavailable") as caught:
            await repo.save_match_detail(101, _payload())

        self.assertIs(caught.exception, original_error)
        snapshot_repo.save_equipment_snapshot.assert_not_called()
        snapshot_repo.save_talent_snapshot.assert_not_called()

    async def test_main_write_failure_does_not_prepare_snapshots(self):
        db = _make_db()
        db.jjc_match_detail.update_one.side_effect = RuntimeError("mongo unavailable")
        snapshot_repo = _make_snapshot_repo()
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        with patch("src.storage.mongo_repos.jjc_inspect_repo.build_equipment_snapshot") as build_snapshot:
            with self.assertRaisesRegex(RuntimeError, "mongo unavailable"):
                await repo.save_match_detail(101, _payload())

        build_snapshot.assert_not_called()

    async def test_successful_main_write_returns_true(self):
        db = _make_db()
        repo = JjcInspectRepo(db=db, snapshot_repo=_make_snapshot_repo())

        result = await repo.save_match_detail(102, {"data": {"match_id": 102}})

        self.assertIs(result, True)
        db.jjc_match_detail.update_one.assert_awaited_once_with(
            {"match_id": 102},
            {"$set": {"cached_at": unittest.mock.ANY, "data": {"match_id": 102}}},
            upsert=True,
        )

    async def test_invalid_match_id_raises_value_error(self):
        db = _make_db()
        repo = JjcInspectRepo(db=db, snapshot_repo=_make_snapshot_repo())

        with self.assertRaises(ValueError):
            await repo.save_match_detail("not-an-integer", _payload())

        db.jjc_match_detail.update_one.assert_not_called()

    async def test_non_integer_numeric_match_id_raises_value_error(self):
        db = _make_db()
        repo = JjcInspectRepo(db=db, snapshot_repo=_make_snapshot_repo())

        with self.assertRaises(ValueError):
            await repo.save_match_detail(102.5, _payload())

        db.jjc_match_detail.update_one.assert_not_called()

    async def test_main_document_is_written_before_snapshot_derivation(self):
        events = []
        db = _make_db()
        snapshot_repo = _make_snapshot_repo()

        async def update_one(*args, **kwargs):
            events.append("match_detail")

        async def save_equipment_snapshot(*args, **kwargs):
            events.append("equipment_snapshot")

        async def save_talent_snapshot(*args, **kwargs):
            events.append("talent_snapshot")

        db.jjc_match_detail.update_one.side_effect = update_one
        snapshot_repo.save_equipment_snapshot.side_effect = save_equipment_snapshot
        snapshot_repo.save_talent_snapshot.side_effect = save_talent_snapshot
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        result = await repo.save_match_detail(103, _payload(103))

        self.assertIs(result, True)
        self.assertEqual(
            events,
            ["match_detail", "equipment_snapshot", "talent_snapshot", "match_detail"],
        )

    async def test_snapshot_failure_keeps_successful_main_write_result(self):
        db = _make_db()
        snapshot_repo = _make_snapshot_repo()
        snapshot_repo.save_equipment_snapshot.side_effect = RuntimeError("snapshot unavailable")
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        with patch("src.storage.mongo_repos.jjc_inspect_repo.logger") as mocked_logger:
            result = await repo.save_match_detail(104, _payload(104))

        self.assertIs(result, True)
        db.jjc_match_detail.update_one.assert_awaited_once()
        mocked_logger.bind.assert_called_once_with(
            match_id=104,
            derivative_type="snapshots",
            derivative_stage="save",
            error="snapshot unavailable",
        )
        mocked_logger.bind.return_value.warning.assert_called_once_with("JJC 对局详情快照派生失败")

    async def test_snapshot_failure_keeps_full_detail_in_primary_document(self):
        db = _make_db()
        snapshot_repo = _make_snapshot_repo()
        snapshot_repo.save_equipment_snapshot.side_effect = RuntimeError("snapshot unavailable")
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        await repo.save_match_detail(105, _payload(105))

        stored_data = db.jjc_match_detail.update_one.await_args.args[1]["$set"]["data"]
        stored_player = stored_data["detail"]["team1"]["players_info"][0]
        self.assertIn("armors", stored_player)
        self.assertIn("talents", stored_player)
        self.assertEqual(stored_player["armors"], [{"pos": 1, "name": "破军"}])
        self.assertEqual(stored_player["talents"], [{"level": 1, "name": "奇穴一"}])
        self.assertNotIn("equipment_snapshot_hash", stored_player)
        self.assertNotIn("talent_snapshot_hash", stored_player)

    async def test_partial_snapshot_failure_keeps_full_detail_in_primary_document(self):
        db = _make_db()
        snapshot_repo = _make_snapshot_repo()
        snapshot_repo.save_talent_snapshot.side_effect = RuntimeError("talent snapshot unavailable")
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        result = await repo.save_match_detail(106, _payload(106))

        self.assertIs(result, True)
        db.jjc_match_detail.update_one.assert_awaited_once()
        snapshot_repo.save_equipment_snapshot.assert_awaited_once()
        snapshot_repo.save_talent_snapshot.assert_awaited_once()
        stored_data = db.jjc_match_detail.update_one.await_args.args[1]["$set"]["data"]
        stored_player = stored_data["detail"]["team1"]["players_info"][0]
        self.assertIn("armors", stored_player)
        self.assertIn("talents", stored_player)
        self.assertNotIn("equipment_snapshot_hash", stored_player)
        self.assertNotIn("talent_snapshot_hash", stored_player)

    async def test_compaction_failure_keeps_full_detail_in_primary_document(self):
        db = _make_db()
        db.jjc_match_detail.update_one.side_effect = [None, RuntimeError("compact unavailable")]
        snapshot_repo = _make_snapshot_repo()
        repo = JjcInspectRepo(db=db, snapshot_repo=snapshot_repo)

        with patch("src.storage.mongo_repos.jjc_inspect_repo.logger") as mocked_logger:
            result = await repo.save_match_detail(107, _payload(107))

        self.assertIs(result, True)
        self.assertEqual(db.jjc_match_detail.update_one.await_count, 2)
        primary_data = db.jjc_match_detail.update_one.await_args_list[0].args[1]["$set"]["data"]
        primary_player = primary_data["detail"]["team1"]["players_info"][0]
        self.assertIn("armors", primary_player)
        self.assertIn("talents", primary_player)
        mocked_logger.bind.assert_called_once_with(
            match_id=107,
            derivative_type="snapshots",
            derivative_stage="compact",
            error="compact unavailable",
        )

    async def test_boolean_and_non_positive_match_ids_raise_value_error(self):
        db = _make_db()
        repo = JjcInspectRepo(db=db, snapshot_repo=_make_snapshot_repo())

        for match_id in (True, 0, -1, "0", "-1"):
            with self.subTest(match_id=match_id):
                with self.assertRaises(ValueError):
                    await repo.save_match_detail(match_id, _payload())

        db.jjc_match_detail.update_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
