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
# Read hydration
# ---------------------------------------------------------------------------


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
        """Player without snapshot hashes does not receive equipment/talent arrays."""
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


# ---------------------------------------------------------------------------
# Unavailable cache support
# ---------------------------------------------------------------------------


class TestLoadMatchDetailUnavailable(unittest.IsolatedAsyncioTestCase):
    """Unavailable docs are returned as-is without snapshot hydration."""

    async def test_load_unavailable_skips_hydration(self):
        doc = {
            "match_id": 500,
            "cached_at": 1234567890.0,
            "data": {
                "match_id": 500,
                "unavailable": True,
                "code": -1,
                "message": "no data found",
                "detail": None,
            },
        }
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock()
        snapshot_repo.load_talent_snapshots = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(500)

        assert result is not None
        self.assertEqual(result["data"]["unavailable"], True)
        self.assertEqual(result["data"]["code"], -1)
        self.assertEqual(result["data"]["message"], "no data found")
        self.assertIsNone(result["data"]["detail"])
        snapshot_repo.load_equipment_snapshots.assert_not_called()
        snapshot_repo.load_talent_snapshots.assert_not_called()

    async def test_load_unavailable_skips_hydration_even_with_players(self):
        """Even if players_info has snapshot hashes, unavailable doc skips hydration."""
        player = _make_player(kungfu="冰心诀", equipment_snapshot_hash="h1")
        doc = _make_match_detail_doc(501, {"team1": _make_team([player])})
        doc["data"]["unavailable"] = True
        db = _mock_db()
        db.jjc_match_detail.find_one.return_value = doc

        snapshot_repo = MagicMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock()
        snapshot_repo.load_talent_snapshots = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        result = await repo.load_match_detail(501)

        assert result is not None
        self.assertTrue(result["data"]["unavailable"])
        snapshot_repo.load_equipment_snapshots.assert_not_called()


class TestSaveMatchDetailUnavailable(unittest.IsolatedAsyncioTestCase):
    """Unavailable payloads skip snapshot extraction entirely."""

    async def test_save_unavailable_skips_snapshot_repo(self):
        payload = {
            "cached_at": 1234567890.0,
            "data": {
                "match_id": 600,
                "unavailable": True,
                "code": -1,
                "message": "no data found",
                "detail": None,
            },
        }
        db = _mock_db()
        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock()
        snapshot_repo.save_talent_snapshot = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        await repo.save_match_detail(600, payload)

        snapshot_repo.save_equipment_snapshot.assert_not_called()
        snapshot_repo.save_talent_snapshot.assert_not_called()
        db.jjc_match_detail.update_one.assert_called_once()
        stored_data = db.jjc_match_detail.update_one.call_args[0][1]["$set"]["data"]
        self.assertTrue(stored_data["unavailable"])
        self.assertEqual(stored_data["code"], -1)

    async def test_save_unavailable_round_trip(self):
        payload = {
            "cached_at": 1234567890.0,
            "data": {
                "match_id": 700,
                "unavailable": True,
                "code": -1,
                "message": "no data found",
                "detail": None,
            },
        }
        db = _mock_db()
        snapshot_repo = MagicMock()
        snapshot_repo.save_equipment_snapshot = AsyncMock()
        snapshot_repo.save_talent_snapshot = AsyncMock()
        snapshot_repo.load_equipment_snapshots = AsyncMock()
        snapshot_repo.load_talent_snapshots = AsyncMock()

        repo = _build_repo(db=db, snapshot_repo=snapshot_repo)
        await repo.save_match_detail(700, payload)

        loaded_doc = {
            "match_id": 700,
            "cached_at": 1234567890.0,
            "data": {
                "match_id": 700,
                "unavailable": True,
                "code": -1,
                "message": "no data found",
                "detail": None,
            },
        }
        db.jjc_match_detail.find_one.return_value = loaded_doc

        result = await repo.load_match_detail(700)
        assert result is not None
        self.assertTrue(result["data"]["unavailable"])
        self.assertIsNone(result["data"]["detail"])
        snapshot_repo.load_equipment_snapshots.assert_not_called()
        snapshot_repo.load_talent_snapshots.assert_not_called()


# ---------------------------------------------------------------------------
# Service-level unavailable integration tests
# ---------------------------------------------------------------------------


class TestGetMatchDetailUnavailableService(unittest.IsolatedAsyncioTestCase):
    """JjcRankingInspectService.get_match_detail handles unavailable flow."""

    async def test_cached_unavailable_returned_without_tuilan(self):
        """Cache hit on unavailable doc returns it without calling tuilan at all."""
        from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService

        cached_doc = {
            "match_id": 999,
            "cached_at": 1234567890.0,
            "data": {
                "match_id": 999,
                "unavailable": True,
                "code": -1,
                "message": "no data found",
                "detail": None,
            },
        }
        cache_repo = MagicMock()
        cache_repo.load_match_detail = AsyncMock(return_value=cached_doc)

        match_detail_client = MagicMock()
        match_detail_client.get_match_detail_obj = MagicMock()

        service = JjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=match_detail_client,
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )

        result = await service.get_match_detail(match_id=999)

        self.assertFalse(result.get("error"))
        self.assertTrue(result.get("unavailable"))
        self.assertEqual(result.get("code"), -1)
        self.assertEqual(result.get("message"), "no data found")
        self.assertIsNone(result.get("detail"))
        self.assertTrue(result.get("cache", {}).get("hit"))
        match_detail_client.get_match_detail_obj.assert_not_called()

    async def test_live_no_data_found_saves_unavailable(self):
        """Live response code=-1/msg=no data found saves unavailable, returns stable payload."""
        import asyncio
        from unittest.mock import patch

        from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService
        from src.services.jx3.match_detail import MatchDetailResponse

        cache_repo = MagicMock()
        cache_repo.load_match_detail = AsyncMock(return_value=None)
        cache_repo.save_match_detail = AsyncMock()

        no_data_response = MatchDetailResponse(code=-1, msg="no data found", data=None)

        match_detail_client = MagicMock()
        match_detail_client.get_match_detail_obj = MagicMock(return_value=no_data_response)

        service = JjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=match_detail_client,
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )

        async def _to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch.object(asyncio, "to_thread", _to_thread):
            result = await service.get_match_detail(match_id=888)

        self.assertFalse(result.get("error"))
        self.assertTrue(result.get("unavailable"))
        self.assertEqual(result.get("code"), -1)
        self.assertEqual(result.get("message"), "no data found")
        self.assertEqual(result.get("match_id"), 888)
        self.assertIsNone(result.get("detail"))
        self.assertFalse(result.get("cache", {}).get("hit"))

        cache_repo.save_match_detail.assert_called_once()
        call_args = cache_repo.save_match_detail.call_args[0]
        self.assertEqual(call_args[0], 888)  # match_id
        saved_payload = call_args[1]
        self.assertEqual(saved_payload["data"]["match_id"], 888)
        self.assertTrue(saved_payload["data"]["unavailable"])
        self.assertEqual(saved_payload["data"]["code"], -1)
        self.assertEqual(saved_payload["data"]["message"], "no data found")

    async def test_live_other_nonzero_code_still_errors(self):
        """code=-2 or other nonzero codes with no data still return error as before."""
        import asyncio
        from unittest.mock import patch

        from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService
        from src.services.jx3.match_detail import MatchDetailResponse

        cache_repo = MagicMock()
        cache_repo.load_match_detail = AsyncMock(return_value=None)
        cache_repo.save_match_detail = AsyncMock()

        error_response = MatchDetailResponse(code=-2, msg="server error", data=None)

        match_detail_client = MagicMock()
        match_detail_client.get_match_detail_obj = MagicMock(return_value=error_response)

        service = JjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=match_detail_client,
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )

        async def _to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch.object(asyncio, "to_thread", _to_thread):
            result = await service.get_match_detail(match_id=777)

        self.assertTrue(result.get("error"))
        self.assertEqual(result.get("code"), -2)
        cache_repo.save_match_detail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
