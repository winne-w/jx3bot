from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Dict, List

from src.storage.mongo_repos.jjc_match_participant_repo import (
    DETAIL_SOURCE_MATCH_DETAIL,
    SYNC_STATUS_NOT_SYNCED,
    JjcMatchParticipantRepo,
)


def _player(global_id: str = "", **kwargs: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "global_id": global_id,
        "role_name": "角色" + (global_id or "missing"),
        "server": "梦江南",
        "kungfu": "冰心诀",
    }
    data.update(kwargs)
    return data


def _team(players: List[Dict[str, Any]], won: bool = False) -> Dict[str, Any]:
    return {"won": won, "players_info": players}


def _payload(
    team1: List[Dict[str, Any]],
    team2: List[Dict[str, Any]],
    *,
    match_type: Any = 3,
    match_time: Any = None,
) -> Dict[str, Any]:
    basic_info: Dict[str, Any] = {
        "start_time": 1710000000,
        "duration": 120,
        "grade": 12,
    }
    if match_type is not None:
        basic_info["match_type"] = match_type
    detail: Dict[str, Any] = {
        "basic_info": basic_info,
        "team1": _team(team1, won=True),
        "team2": _team(team2, won=False),
    }
    if match_time is not None:
        detail["match_time"] = match_time
    return {
        "match_id": 1001,
        "cached_at": 1710000010.0,
        "detail": detail,
    }


class TestJjcMatchParticipantRepoBuild(unittest.TestCase):
    def test_extracts_explicit_3v3_players(self) -> None:
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
        )
        seen_doc = {
            "status": "detail_saved",
            "match_time": 1710000000,
            "detail_saved_at": 1710000020.0,
            "source_identity_key": "global_id:g1",
        }

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload, seen_doc)

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["match_id"], 1001)
        self.assertEqual(rows[0]["global_id"], "g1")
        self.assertEqual(rows[0]["team_key"], "team1")
        self.assertEqual(rows[0]["won"], True)
        self.assertEqual(rows[0]["sync_status"], "detail_saved")
        self.assertEqual(rows[0]["detail_saved_at"], 1710000020.0)
        self.assertTrue(rows[0]["detail_available"])
        self.assertEqual(rows[0]["detail_source"], DETAIL_SOURCE_MATCH_DETAIL)
        self.assertFalse(rows[0]["match_type_inferred"])

    def test_infers_3v3_from_six_players(self) -> None:
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
            match_type=None,
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["match_type_inferred"] for row in rows))
        self.assertEqual(rows[0]["match_type"], 3)

    def test_skips_non_3v3_explicit_match_type(self) -> None:
        payload = _payload(
            [_player("g1"), _player("g2")],
            [_player("g3"), _player("g4")],
            match_type=2,
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual(rows, [])

    def test_skips_non_3v3_when_not_inferable(self) -> None:
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5")],
            match_type=None,
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual(rows, [])

    def test_skips_players_missing_global_id(self) -> None:
        payload = _payload(
            [_player("g1"), _player("", role_name="缺失"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual([row["global_id"] for row in rows], ["g1", "g3", "g4", "g5", "g6"])

    def test_duplicate_global_id_first_wins(self) -> None:
        payload = _payload(
            [_player("g1", role_name="第一个"), _player("g1", role_name="第二个"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        g1_rows = [row for row in rows if row["global_id"] == "g1"]
        self.assertEqual(len(g1_rows), 1)
        self.assertEqual(g1_rows[0]["role_name"], "第一个")
        self.assertEqual(g1_rows[0]["player_index"], 0)

    def test_sync_status_falls_back_to_not_synced(self) -> None:
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload, seen_doc=None)

        self.assertEqual(rows[0]["sync_status"], SYNC_STATUS_NOT_SYNCED)
        self.assertIsNone(rows[0]["detail_saved_at"])
        self.assertIsNone(rows[0]["source_identity_key"])

    def test_uses_outer_cached_at_for_wrapped_payload(self) -> None:
        payload = {
            "cached_at": 1710000099.0,
            "data": _payload(
                [_player("g1"), _player("g2"), _player("g3")],
                [_player("g4"), _player("g5"), _player("g6")],
            ),
        }

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload, seen_doc=None)

        self.assertEqual(rows[0]["cached_at"], 1710000099.0)

    def test_projects_split_score_fields(self) -> None:
        payload = _payload(
            [_player("g1", mmr=2660, total_score=2528, score=2501), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual(rows[0]["tuilan_score"], 2660)
        self.assertEqual(rows[0]["game_score"], 2528)
        self.assertEqual(rows[0]["game_score_source"], "total_score")
        self.assertEqual(rows[0]["raw_mmr"], 2660)
        self.assertEqual(rows[0]["raw_score"], 2501)
        self.assertEqual(rows[0]["raw_total_score"], 2528)
        self.assertEqual(rows[0]["total_mmr"], 2528)

    def test_game_score_falls_back_to_score_when_total_score_missing(self) -> None:
        payload = _payload(
            [_player("g1", mmr=2660, score=2501), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual(rows[0]["tuilan_score"], 2660)
        self.assertEqual(rows[0]["game_score"], 2501)
        self.assertEqual(rows[0]["game_score_source"], "score")
        self.assertIsNone(rows[0]["raw_total_score"])

    def test_match_time_uses_match_occurrence_time_not_cache_time(self) -> None:
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
            match_time=1710001234,
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual(rows[0]["match_time"], 1710001234)
        self.assertNotEqual(rows[0]["match_time"], payload["cached_at"])

    def test_assigns_current_season_at_or_after_boundary(self) -> None:
        season_start_time = 1777228800
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
            match_time=season_start_time,
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(
            1001,
            payload,
            current_season="新赛季",
            season_start_time=season_start_time,
        )

        self.assertTrue(all(row["season_id"] == "新赛季" for row in rows))

    def test_leaves_preseason_and_missing_time_unassigned(self) -> None:
        season_start_time = 1777228800
        for match_time in (season_start_time - 1, None):
            payload = _payload(
                [_player("g1"), _player("g2"), _player("g3")],
                [_player("g4"), _player("g5"), _player("g6")],
                match_time=match_time,
            )

            rows = JjcMatchParticipantRepo.build_participants_from_match_detail(
                1001,
                payload,
                current_season="新赛季",
                season_start_time=season_start_time,
            )

            self.assertTrue(all(row["season_id"] is None for row in rows))

    def test_detail_source_constants(self) -> None:
        payload = _payload(
            [_player("g1"), _player("g2"), _player("g3")],
            [_player("g4"), _player("g5"), _player("g6")],
        )

        rows = JjcMatchParticipantRepo.build_participants_from_match_detail(1001, payload)

        self.assertEqual(JjcMatchParticipantRepo.COLLECTION_NAME, "jjc_match_participants")
        self.assertEqual(JjcMatchParticipantRepo.DETAIL_SOURCE_MATCH_DETAIL, "match_detail")
        self.assertEqual(JjcMatchParticipantRepo.SYNC_STATUS_NOT_SYNCED, "not_synced")
        self.assertEqual(rows[0]["detail_source"], JjcMatchParticipantRepo.DETAIL_SOURCE_MATCH_DETAIL)


class _EmptyCursor:
    def sort(self, *args: Any, **kwargs: Any) -> "_EmptyCursor":
        return self

    def skip(self, *args: Any, **kwargs: Any) -> "_EmptyCursor":
        return self

    def limit(self, *args: Any, **kwargs: Any) -> "_EmptyCursor":
        return self

    async def to_list(self, length: int) -> List[Dict[str, Any]]:
        return []


class _QueryCapturingParticipantCollection:
    def __init__(self) -> None:
        self.count_queries: List[Dict[str, Any]] = []
        self.find_queries: List[Dict[str, Any]] = []

    async def count_documents(self, query: Dict[str, Any]) -> int:
        self.count_queries.append(query)
        return 0

    def find(self, query: Dict[str, Any]) -> _EmptyCursor:
        self.find_queries.append(query)
        return _EmptyCursor()


class TestJjcMatchParticipantRepoQuery(unittest.IsolatedAsyncioTestCase):
    async def test_current_season_query_also_enforces_season_start_time(self) -> None:
        collection = _QueryCapturingParticipantCollection()
        repo = JjcMatchParticipantRepo(db=SimpleNamespace(jjc_match_participants=collection))

        await repo.list_local_3v3_matches_by_global_id(
            "g1",
            season_id="暗影千机",
            season_start_time=1776960000,
        )

        expected = {"$gte": 1776960000}
        self.assertEqual(collection.count_queries[0]["match_time"], expected)
        self.assertEqual(collection.find_queries[0]["match_time"], expected)


if __name__ == "__main__":
    unittest.main()
