from __future__ import annotations

import copy
import unittest
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo


def _make_player(**kw: Any) -> Dict[str, Any]:
    return dict(kw)


def _make_match_detail_doc(match_id: int, teams: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "match_id": match_id,
        "cached_at": 1234567890.0,
        "data": {
            "match_id": match_id,
            "detail": teams,
        },
    }


def _make_team(players: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"players_info": players}


# ---------------------------------------------------------------------------
# helpers to build mock repos
# ---------------------------------------------------------------------------


def _mock_db(collection_name: str = "jjc_match_detail") -> MagicMock:
    col = MagicMock()
    col.find_one = AsyncMock()
    col.update_one = AsyncMock()
    db = MagicMock()
    setattr(db, collection_name, col)
    return db


def _build_repo(db=None, snapshot_repo=None):
    repo_kwargs: Dict[str, Any] = {"db": db} if db is not None else {}
    if snapshot_repo is not None:
        repo_kwargs["snapshot_repo"] = snapshot_repo
    return JjcInspectRepo(**repo_kwargs)


# ---------------------------------------------------------------------------
# Stage 3: read hydration
# ---------------------------------------------------------------------------


class TestLoadMatchDetailOldStructure(unittest.IsolatedAsyncioTestCase):
    """Old-format players with armors/talents are left unchanged."""

    async def test_old_structure_unchanged(self):
        player = _make_player(kungfu="冰心诀", armors=[{"pos": 1, "name": "破军"}], talents=[{"level": 1, "name": "奇穴一"}])
        doc = _make_match_detail_doc(100, {"team1": _make_team([player])})
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock()
        snapshot_repo.load_talent_snapshots = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(100)

        assert result is not None
        hydrated = result["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(hydrated["armors"], [{"pos": 1, "name": "破军"}])
        self.assertEqual(hydrated["talents"], [{"level": 1, "name": "奇穴一"}])
        # No snapshot queries should fire for old-format players
        snapshot_repo.load_equipment_snapshots.assert_not_called()
        snapshot_repo.load_talent_snapshots.assert_not_called()

    async def test_old_structure_with_no_talents(self):
        player = _make_player(kungfu="冰心诀", armors=[{"pos": 1, "name": "破军"}])
        doc = _make_match_detail_doc(101, {"team1": _make_team([player])})
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock()
        snapshot_repo.load_talent_snapshots = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(101)

        assert result is not None
        hydrated = result["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(hydrated["armors"], [{"pos": 1, "name": "破军"}])
        self.assertNotIn("talents", hydrated)


class TestLoadMatchDetailHydration(unittest.IsolatedAsyncioTestCase):
    """New-format players with only hashes get armors/talents filled in."""

    async def test_hydrates_from_snapshots(self):
        player = _make_player(kungfu="冰心诀", equipment_snapshot_hash="h1", talent_snapshot_hash="t1")
        doc = _make_match_detail_doc(200, {"team1": _make_team([player])})
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        equip_doc = {"snapshot_hash": "h1", "armors": [{"pos": 1, "name": "破军"}]}
        talent_doc = {"snapshot_hash": "t1", "talents": [{"level": 1, "name": "奇穴一"}]}

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock(return_value={"h1": equip_doc})
        snapshot_repo.load_talent_snapshots = AsyncMock(return_value={"t1": talent_doc})

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(200)

        assert result is not None
        hydrated = result["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(hydrated["armors"], [{"pos": 1, "name": "破军"}])
        self.assertEqual(hydrated["talents"], [{"level": 1, "name": "奇穴一"}])
        self.assertEqual(hydrated["equipment_snapshot_hash"], "h1")
        self.assertEqual(hydrated["talent_snapshot_hash"], "t1")

    async def test_player_without_any_indicators_left_unchanged(self):
        """Old-format player without armors/talents and without hash keys is left unchanged."""
        player = _make_player(kungfu="冰心诀")
        doc = _make_match_detail_doc(201, {"team1": _make_team([player])})
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock()
        snapshot_repo.load_talent_snapshots = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(201)

        assert result is not None
        hydrated = result["data"]["detail"]["team1"]["players_info"][0]
        self.assertNotIn("armors", hydrated)
        self.assertNotIn("talents", hydrated)


class TestLoadMatchDetailMissingSnapshots(unittest.IsolatedAsyncioTestCase):
    """Missing snapshots yield empty arrays and a warning; the match still loads."""

    async def test_missing_equipment_snapshot(self):
        player = _make_player(kungfu="冰心诀", equipment_snapshot_hash="h_missing", talent_snapshot_hash="t1")
        doc = _make_match_detail_doc(300, {"team1": _make_team([player])})
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        talent_doc = {"snapshot_hash": "t1", "talents": [{"level": 2, "name": "奇穴二"}]}

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock(return_value={})
        snapshot_repo.load_talent_snapshots = AsyncMock(return_value={"t1": talent_doc})

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(300)

        assert result is not None
        hydrated = result["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(hydrated["armors"], [])
        self.assertEqual(hydrated["talents"], [{"level": 2, "name": "奇穴二"}])

    async def test_missing_talent_snapshot(self):
        player = _make_player(kungfu="冰心诀", equipment_snapshot_hash="h1", talent_snapshot_hash="t_missing")
        doc = _make_match_detail_doc(301, {"team1": _make_team([player])})
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        equip_doc = {"snapshot_hash": "h1", "armors": [{"pos": 1, "name": "破军"}]}

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock(return_value={"h1": equip_doc})
        snapshot_repo.load_talent_snapshots = AsyncMock(return_value={})

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(301)

        assert result is not None
        hydrated = result["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(hydrated["armors"], [{"pos": 1, "name": "破军"}])
        self.assertEqual(hydrated["talents"], [])


class TestLoadMatchDetailSharedHashes(unittest.IsolatedAsyncioTestCase):
    """Multiple players sharing the same hash trigger only one batch query."""

    async def test_shared_hash_batch_queries_once(self):
        p1 = _make_player(kungfu="冰心诀", equipment_snapshot_hash="h_shared")
        p2 = _make_player(kungfu="云裳心经", equipment_snapshot_hash="h_shared")
        doc = _make_match_detail_doc(400, {
            "team1": _make_team([p1]),
            "team2": _make_team([p2]),
        })
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        equip_doc = {"snapshot_hash": "h_shared", "armors": [{"pos": 1, "name": "共用装备"}]}

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock(return_value={"h_shared": equip_doc})
        snapshot_repo.load_talent_snapshots = AsyncMock(return_value={})

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(400)

        assert result is not None
        # Both players hydrated
        for team_key in ("team1", "team2"):
            hydrated = result["data"]["detail"][team_key]["players_info"][0]
            self.assertEqual(hydrated["armors"], [{"pos": 1, "name": "共用装备"}])

        # Only one batch query (deduplicated hash)
        snapshot_repo.load_equipment_snapshots.assert_called_once()
        args = snapshot_repo.load_equipment_snapshots.call_args[0][0]
        self.assertEqual(args, ["h_shared"])


class TestLoadMatchDetailNoSnapshotRepo(unittest.IsolatedAsyncioTestCase):
    """Without snapshot_repo injected, load returns docs as-is (no hydration)."""

    async def test_no_snapshot_repo_returns_raw_doc(self):
        player = _make_player(kungfu="冰心诀", equipment_snapshot_hash="h1")
        doc = _make_match_detail_doc(500, {"team1": _make_team([player])})
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        repo = _build_repo(db=db)
        result = await repo.load_match_detail(500)

        assert result is not None
        hydrated = result["data"]["detail"]["team1"]["players_info"][0]
        self.assertNotIn("armors", hydrated)
        self.assertNotIn("talents", hydrated)
        self.assertEqual(hydrated["equipment_snapshot_hash"], "h1")


# ---------------------------------------------------------------------------
# Stage 4: write snapshot extraction
# ---------------------------------------------------------------------------


class TestSaveMatchDetailExtractsSnapshots(unittest.IsolatedAsyncioTestCase):
    """Saving a match_detail stores armors/talents in snapshots and keeps hashes in the stored doc."""

    async def test_extracts_equipment_and_talent_snapshots(self):
        armors = [{"pos": 1, "ui_id": "a", "name": "破军"}]
        talents = [{"level": 1, "id": "t1", "name": "奇穴一"}]
        player = _make_player(kungfu="冰心诀", armors=copy.deepcopy(armors), talents=copy.deepcopy(talents))
        payload_data = {
            "match_id": 600,
            "detail": {"team1": _make_team([player])},
        }
        payload = {"cached_at": 1234567890.0, "data": payload_data}

        db = _mock_db()
        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock()
        snapshot_repo.save_talent_snapshot = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        await repo.save_match_detail(600, payload)

        # Snapshot saves called
        snapshot_repo.save_equipment_snapshot.assert_called_once()
        snapshot_repo.save_talent_snapshot.assert_called_once()

        # The match_detail update should have hashes, not full arrays
        db.jjc_match_detail.update_one.assert_called_once()
        call_args, _ = db.jjc_match_detail.update_one.call_args
        stored_data = call_args[1]["$set"]["data"]
        stored_player = stored_data["detail"]["team1"]["players_info"][0]
        self.assertNotIn("armors", stored_player)
        self.assertNotIn("talents", stored_player)
        self.assertIn("equipment_snapshot_hash", stored_player)
        self.assertIn("talent_snapshot_hash", stored_player)
        self.assertEqual(len(stored_player["equipment_snapshot_hash"]), 64)
        self.assertEqual(len(stored_player["talent_snapshot_hash"]), 64)

        # Original payload NOT mutated
        self.assertIn("armors", payload_data["detail"]["team1"]["players_info"][0])
        self.assertIn("talents", payload_data["detail"]["team1"]["players_info"][0])

    async def test_player_with_only_armors(self):
        armors = [{"pos": 1, "name": "破军"}]
        player = _make_player(kungfu="冰心诀", armors=copy.deepcopy(armors))
        payload_data = {
            "match_id": 601,
            "detail": {"team1": _make_team([player])},
        }
        payload = {"cached_at": 1234567890.0, "data": payload_data}

        db = _mock_db()
        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock()
        snapshot_repo.save_talent_snapshot = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        await repo.save_match_detail(601, payload)

        snapshot_repo.save_equipment_snapshot.assert_called_once()
        snapshot_repo.save_talent_snapshot.assert_not_called()

        call_args, _ = db.jjc_match_detail.update_one.call_args
        stored_player = call_args[1]["$set"]["data"]["detail"]["team1"]["players_info"][0]
        self.assertIn("equipment_snapshot_hash", stored_player)
        self.assertNotIn("armors", stored_player)
        self.assertNotIn("talent_snapshot_hash", stored_player)
        self.assertNotIn("talents", stored_player)

    async def test_empty_armors_not_saved(self):
        player = _make_player(kungfu="冰心诀", armors=[], talents=[])
        payload_data = {
            "match_id": 602,
            "detail": {"team1": _make_team([player])},
        }
        payload = {"cached_at": 1234567890.0, "data": payload_data}

        db = _mock_db()
        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock()
        snapshot_repo.save_talent_snapshot = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        await repo.save_match_detail(602, payload)

        snapshot_repo.save_equipment_snapshot.assert_not_called()
        snapshot_repo.save_talent_snapshot.assert_not_called()

        call_args, _ = db.jjc_match_detail.update_one.call_args
        stored_player = call_args[1]["$set"]["data"]["detail"]["team1"]["players_info"][0]
        self.assertNotIn("equipment_snapshot_hash", stored_player)


class TestSaveMatchDetailRoundTrip(unittest.IsolatedAsyncioTestCase):
    """Save then load restores full armors/talents."""

    async def test_round_trip(self):
        armors = [{"pos": 1, "ui_id": "a", "name": "破军"}, {"pos": 2, "ui_id": "b", "name": "破虏"}]
        talents = [{"level": 1, "id": "t1", "name": "奇穴一"}, {"level": 2, "id": "t2", "name": "奇穴二"}]

        p1 = _make_player(kungfu="冰心诀", armors=copy.deepcopy(armors), talents=copy.deepcopy(talents))
        p2 = _make_player(kungfu="云裳心经", armors=copy.deepcopy(armors), talents=copy.deepcopy(talents))
        payload_data = {
            "match_id": 700,
            "detail": {
                "team1": _make_team([p1]),
                "team2": _make_team([p2]),
            },
        }
        payload = {"cached_at": 1234567890.0, "data": payload_data}

        # Internal stores so save + load behave consistently
        _equip_store: Dict[str, Dict[str, Any]] = {}
        _talent_store: Dict[str, Dict[str, Any]] = {}

        async def _save_equip(hash_val, armors_list, seen_at=None):
            _equip_store[hash_val] = {"snapshot_hash": hash_val, "armors": armors_list}

        async def _load_equip(hashes):
            return {h: _equip_store[h] for h in hashes if h in _equip_store}

        async def _save_talent(hash_val, talents_list, seen_at=None):
            _talent_store[hash_val] = {"snapshot_hash": hash_val, "talents": talents_list}

        async def _load_talent(hashes):
            return {h: _talent_store[h] for h in hashes if h in _talent_store}

        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock(side_effect=_save_equip)
        snapshot_repo.save_talent_snapshot = AsyncMock(side_effect=_save_talent)
        snapshot_repo.load_equipment_snapshots = AsyncMock(side_effect=_load_equip)
        snapshot_repo.load_talent_snapshots = AsyncMock(side_effect=_load_talent)

        # --- Save ---
        db = _mock_db()
        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)

        # Capture what was written to jjc_match_detail
        _saved_data: Dict[str, Any] = {}

        async def _update_one(filter_doc, set_doc, upsert=False):
            _saved_data["data"] = set_doc["$set"]["data"]

        db.jjc_match_detail.update_one.side_effect = _update_one

        await repo.save_match_detail(700, payload)

        # Verify snapshots were saved
        self.assertEqual(len(_equip_store), 1)  # deduplicated by hash
        self.assertEqual(len(_talent_store), 1)

        # --- Load ---
        load_doc = _make_match_detail_doc(700, _saved_data["data"]["detail"])
        db2 = _mock_db()
        db2.jjc_match_detail.find_one.return_value = load_doc

        repo2 = _build_repo(db=db2, snapshot_repo=snapshot_repo)
        result = await repo2.load_match_detail(700)

        assert result is not None
        for team_key in ("team1", "team2"):
            hydrated = result["data"]["detail"][team_key]["players_info"][0]
            self.assertEqual(len(hydrated["armors"]), 2)
            self.assertEqual(hydrated["armors"][0]["name"], "破军")
            self.assertEqual(hydrated["armors"][1]["name"], "破虏")
            self.assertEqual(len(hydrated["talents"]), 2)
            self.assertEqual(hydrated["talents"][0]["name"], "奇穴一")
            self.assertEqual(hydrated["talents"][1]["name"], "奇穴二")
            # Hash fields remain (not stripped during hydration)
            self.assertIn("equipment_snapshot_hash", hydrated)
            self.assertIn("talent_snapshot_hash", hydrated)


class TestSaveMatchDetailSnapshotFailure(unittest.IsolatedAsyncioTestCase):
    """When snapshot save fails, the exception propagates and match_detail is NOT written."""

    async def test_equipment_snapshot_failure_prevents_save(self):
        armors = [{"pos": 1, "name": "破军"}]
        player = _make_player(kungfu="冰心诀", armors=copy.deepcopy(armors))
        payload_data = {
            "match_id": 800,
            "detail": {"team1": _make_team([player])},
        }
        payload = {"cached_at": 1234567890.0, "data": payload_data}

        db = _mock_db()
        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock(side_effect=RuntimeError("db down"))
        snapshot_repo.save_talent_snapshot = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)

        with self.assertRaises(RuntimeError):
            await repo.save_match_detail(800, payload)

        # jjc_match_detail must NOT be updated
        db.jjc_match_detail.update_one.assert_not_called()

    async def test_talent_snapshot_failure_prevents_save(self):
        talents = [{"level": 1, "name": "奇穴一"}]
        player = _make_player(kungfu="冰心诀", talents=copy.deepcopy(talents))
        payload_data = {
            "match_id": 801,
            "detail": {"team1": _make_team([player])},
        }
        payload = {"cached_at": 1234567890.0, "data": payload_data}

        db = _mock_db()
        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock()
        snapshot_repo.save_talent_snapshot = AsyncMock(side_effect=RuntimeError("db down"))

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)

        with self.assertRaises(RuntimeError):
            await repo.save_match_detail(801, payload)

        db.jjc_match_detail.update_one.assert_not_called()


class TestSaveMatchDetailNoSnapshotRepo(unittest.IsolatedAsyncioTestCase):
    """Without snapshot_repo, data is stored as-is (no extraction)."""

    async def test_no_snapshot_repo_stores_as_is(self):
        armors = [{"pos": 1, "name": "破军"}]
        talents = [{"level": 1, "name": "奇穴一"}]
        player = _make_player(kungfu="冰心诀", armors=copy.deepcopy(armors), talents=copy.deepcopy(talents))
        payload_data = {
            "match_id": 900,
            "detail": {"team1": _make_team([player])},
        }
        payload = {"cached_at": 1234567890.0, "data": payload_data}

        db = _mock_db()
        repo = _build_repo(db=db)

        await repo.save_match_detail(900, payload)

        db.jjc_match_detail.update_one.assert_called_once()
        call_args, _ = db.jjc_match_detail.update_one.call_args
        stored_player = call_args[1]["$set"]["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(stored_player["armors"], armors)
        self.assertEqual(stored_player["talents"], talents)
        self.assertNotIn("equipment_snapshot_hash", stored_player)
        self.assertNotIn("talent_snapshot_hash", stored_player)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestLoadMatchDetailEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_match_id_returns_none(self):
        repo = _build_repo()
        result = await repo.load_match_detail("not_a_number")
        self.assertIsNone(result)

    async def test_none_doc_returns_none(self):
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = None
        repo = _build_repo(db=db)
        result = await repo.load_match_detail(999)
        self.assertIsNone(result)

    async def test_doc_without_data_field(self):
        doc = {"match_id": 1000, "cached_at": 1234567890.0}
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc
        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock()
        snapshot_repo.load_talent_snapshots = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(1000)
        assert result is not None
        # No crash; no hydration attempted


class TestSaveMatchDetailEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_match_id_is_noop(self):
        db = _mock_db()
        repo = _build_repo(db=db)
        await repo.save_match_detail("not_a_number", {"data": {}})
        db.jjc_match_detail.update_one.assert_not_called()

    async def test_payload_without_data_key(self):
        payload = {"cached_at": 1234567890.0}
        db = _mock_db()
        repo = _build_repo(db=db)
        await repo.save_match_detail(1100, payload)
        db.jjc_match_detail.update_one.assert_called_once()
        # Uses payload itself as data (old codepath)


if __name__ == "__main__":
    unittest.main()
