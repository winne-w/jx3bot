from __future__ import annotations

import copy
import unittest
from typing import Any, Dict


class _FakeMatchupRepo:
    """The normalization unit must not query persistence."""

    def search_matchups(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        raise AssertionError("normalize_filters() must not query the matchup repository")


class _RecordingMatchupRepo:
    def __init__(self, result: Dict[str, Any]) -> None:
        self.result = result
        self.calls = []

    async def search_matchups(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(filters)
        return self.result


class TestJjcMatchupFilterNormalization(unittest.TestCase):
    def _request(self, **overrides: Any) -> Dict[str, Any]:
        request = {
            "start_time": 1_700_000_000,
            "end_time": 1_700_086_400,
            "score_min": 0,
            "score_max": 1_000_000,
        }
        request.update(overrides)
        return request

    def _normalize(self, request: Dict[str, Any]) -> Any:
        try:
            from src.services.jx3.jjc_matchup import JjcMatchupFilters, JjcMatchupService
        except ModuleNotFoundError as error:
            if error.name == "src.services.jx3.jjc_matchup":
                self.fail("JJC matchup request normalization has not been implemented")
            raise

        normalized = JjcMatchupService(_FakeMatchupRepo()).normalize_filters(request)
        self.assertIsInstance(normalized, JjcMatchupFilters)
        return normalized

    def test_accepts_a_positive_time_window_of_exactly_fourteen_days(self) -> None:
        start_time = 1_700_000_000

        normalized = self._normalize(self._request(
            start_time=start_time,
            end_time=start_time + 14 * 24 * 60 * 60,
        ))

        self.assertEqual(normalized.start_time, start_time)
        self.assertEqual(normalized.end_time, start_time + 14 * 24 * 60 * 60)

    def test_rejects_missing_time_bounds(self) -> None:
        for missing_field in ("start_time", "end_time"):
            with self.subTest(missing_field=missing_field):
                request = self._request()
                del request[missing_field]
                with self.assertRaises(ValueError):
                    self._normalize(request)

    def test_rejects_non_positive_time_bounds(self) -> None:
        invalid_requests = (
            {"start_time": 0},
            {"end_time": 0},
            {"start_time": -1},
            {"end_time": -1},
        )

        for overrides in invalid_requests:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self._normalize(self._request(**overrides))

    def test_rejects_non_integer_time_bounds_including_bool(self) -> None:
        invalid_values = (True, False, 1.0, "1700000000")

        for field in ("start_time", "end_time"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self._normalize(self._request(**{field: value}))

    def test_rejects_reversed_or_over_fourteen_day_time_windows(self) -> None:
        start_time = 1_700_000_000
        invalid_windows = (
            (start_time, start_time),
            (start_time + 1, start_time),
            (start_time, start_time + 14 * 24 * 60 * 60 + 1),
        )

        for invalid_start, invalid_end in invalid_windows:
            with self.subTest(start_time=invalid_start, end_time=invalid_end):
                with self.assertRaises(ValueError):
                    self._normalize(self._request(
                        start_time=invalid_start,
                        end_time=invalid_end,
                    ))

    def test_accepts_score_interval_endpoints(self) -> None:
        normalized = self._normalize(self._request(score_min=0, score_max=1_000_000))

        self.assertEqual(normalized.score_min, 0)
        self.assertEqual(normalized.score_max, 1_000_000)

    def test_rejects_missing_score_bounds(self) -> None:
        for missing_field in ("score_min", "score_max"):
            with self.subTest(missing_field=missing_field):
                request = self._request()
                del request[missing_field]
                with self.assertRaises(ValueError):
                    self._normalize(request)

    def test_rejects_out_of_range_score_bounds(self) -> None:
        invalid_requests = (
            {"score_min": -1},
            {"score_max": -1},
            {"score_min": 1_000_001},
            {"score_max": 1_000_001},
        )

        for overrides in invalid_requests:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self._normalize(self._request(**overrides))

    def test_rejects_non_integer_score_bounds_including_bool(self) -> None:
        invalid_values = (True, False, 12.0, "12")

        for field in ("score_min", "score_max"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self._normalize(self._request(**{field: value}))

    def test_rejects_score_ranges_without_a_strictly_increasing_interval(self) -> None:
        for score_min, score_max in ((500, 500), (501, 500)):
            with self.subTest(score_min=score_min, score_max=score_max):
                with self.assertRaises(ValueError):
                    self._normalize(self._request(score_min=score_min, score_max=score_max))

    def test_defaults_both_kungfu_lists_to_empty(self) -> None:
        normalized = self._normalize(self._request())

        self.assertEqual(normalized.team_a_kungfu_ids, [])
        self.assertEqual(normalized.team_b_kungfu_ids, [])

    def test_sorts_kungfu_ids_and_preserves_duplicates(self) -> None:
        normalized = self._normalize(self._request(
            team_a_kungfu_ids=[10080, 10001, 10080],
            team_b_kungfu_ids=[10242, 10002, 10002],
        ))

        self.assertEqual(normalized.team_a_kungfu_ids, [10001, 10080, 10080])
        self.assertEqual(normalized.team_b_kungfu_ids, [10002, 10002, 10242])

    def test_accepts_unknown_but_well_formed_historical_kungfu_ids_on_either_side(self) -> None:
        for field in ("team_a_kungfu_ids", "team_b_kungfu_ids"):
            with self.subTest(field=field):
                normalized = self._normalize(self._request(**{field: [9_999_991]}))
                self.assertEqual(getattr(normalized, field), [9_999_991])

    def test_rejects_non_list_kungfu_filters_and_more_than_three_items(self) -> None:
        for field in ("team_a_kungfu_ids", "team_b_kungfu_ids"):
            for value in (None, (10001,), 10001, {"id": 10001}):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self._normalize(self._request(**{field: value}))
            with self.subTest(field=field, value=[1, 2, 3, 4]):
                with self.assertRaises(ValueError):
                    self._normalize(self._request(**{field: [1, 2, 3, 4]}))

    def test_rejects_non_positive_or_non_integer_kungfu_ids_including_bool(self) -> None:
        invalid_ids = (True, False, 0, -1, 10001.0, "10001")

        for field in ("team_a_kungfu_ids", "team_b_kungfu_ids"):
            for invalid_id in invalid_ids:
                with self.subTest(field=field, invalid_id=invalid_id):
                    with self.assertRaises(ValueError):
                        self._normalize(self._request(**{field: [invalid_id]}))

    def test_defaults_page_and_page_size(self) -> None:
        normalized = self._normalize(self._request())

        self.assertEqual(normalized.page, 1)
        self.assertEqual(normalized.page_size, 20)

    def test_accepts_page_interval_endpoints(self) -> None:
        for page in (1, 100_000):
            with self.subTest(page=page):
                normalized = self._normalize(self._request(page=page))
                self.assertEqual(normalized.page, page)

    def test_rejects_non_integer_or_out_of_range_pages_including_bool(self) -> None:
        for page in (True, False, 1.0, "1", 0, 100_001):
            with self.subTest(page=page):
                with self.assertRaises(ValueError):
                    self._normalize(self._request(page=page))

    def test_accepts_each_supported_page_size(self) -> None:
        for page_size in (20, 50, 100):
            with self.subTest(page_size=page_size):
                normalized = self._normalize(self._request(page_size=page_size))
                self.assertEqual(normalized.page_size, page_size)

    def test_rejects_unsupported_or_non_integer_page_sizes_including_bool(self) -> None:
        for page_size in (True, False, 20.0, "20", 0, 21, 101):
            with self.subTest(page_size=page_size):
                with self.assertRaises(ValueError):
                    self._normalize(self._request(page_size=page_size))

    def test_filters_to_dict_returns_copied_normalized_lists_without_mutating_request(self) -> None:
        request = self._request(team_a_kungfu_ids=[10080, 10001, 10080])

        normalized = self._normalize(request)
        filters_dict = normalized.to_dict()
        filters_dict["team_a_kungfu_ids"].append(99999)

        self.assertEqual(request["team_a_kungfu_ids"], [10080, 10001, 10080])
        self.assertEqual(normalized.team_a_kungfu_ids, [10001, 10080, 10080])
        self.assertEqual(normalized.to_dict()["team_a_kungfu_ids"], [10001, 10080, 10080])

    def test_get_meta_returns_fresh_business_data_without_querying_repository(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        service = JjcMatchupService(_FakeMatchupRepo())
        meta = service.get_meta()

        self.assertEqual(
            set(meta),
            {"kungfus", "time_presets", "page_sizes", "limits"},
        )
        self.assertEqual(meta["time_presets"], [1, 3, 7, 14])
        self.assertEqual(meta["page_sizes"], [20, 50, 100])
        self.assertEqual(
            meta["limits"],
            {
                "max_days": 14,
                "score_min": 0,
                "score_max": 1_000_000,
                "max_team_kungfus": 3,
                "max_page": 100_000,
            },
        )
        self.assertNotIn("status_code", meta)
        self.assertTrue(meta["kungfus"])

        meta["kungfus"][0]["name"] = "mutated"
        meta["time_presets"].append(999)
        meta["limits"]["max_days"] = 0
        next_meta = service.get_meta()
        self.assertNotEqual(next_meta["kungfus"][0]["name"], "mutated")
        self.assertEqual(next_meta["time_presets"], [1, 3, 7, 14])
        self.assertEqual(next_meta["limits"]["max_days"], 14)


class TestJjcMatchupSearch(unittest.IsolatedAsyncioTestCase):
    def _request(self, **overrides: Any) -> Dict[str, Any]:
        request = {
            "start_time": 1_700_000_000,
            "end_time": 1_700_086_400,
            "score_min": 0,
            "score_max": 1_000_000,
        }
        request.update(overrides)
        return request

    def _assert_has_no_conclusion_fields(self, value: Any) -> None:
        prohibited = (
            "advantage",
            "disadvantage",
            "confidence",
            "confidence_interval",
            "sample_sufficient",
            "sample_sufficiency",
            "优势",
            "劣势",
            "均势",
            "置信",
            "样本充分",
        )
        if isinstance(value, dict):
            for key, child in value.items():
                self.assertFalse(
                    any(term in str(key).lower() for term in prohibited),
                    "response must not include conclusion field {!r}".format(key),
                )
                self._assert_has_no_conclusion_fields(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_has_no_conclusion_fields(child)

    @staticmethod
    def _raw_result(
        match_count: int = 3,
        bidirectional_match_count: int = 1,
        team_a_wins: int = 3,
        team_b_wins: int = 1,
        missing_score_match_count: int = 2,
        total: int = 999,
        items: Any = None,
    ) -> Dict[str, Any]:
        return {
            "statistics": {
                "match_count": match_count,
                "bidirectional_match_count": bidirectional_match_count,
                "team_a_wins": team_a_wins,
                "team_b_wins": team_b_wins,
                "missing_score_match_count": missing_score_match_count,
            },
            "items": [] if items is None else items,
            "total": total,
        }

    @staticmethod
    def _summary_item(match_id: int, orientations: Any) -> Dict[str, Any]:
        def team(won: bool, prefix: str, score_avg: float) -> Dict[str, Any]:
            return {
                "won": won,
                "players": [
                    {
                        "role_name": "{}-role-{}".format(prefix, index),
                        "server": "server-{}".format(index),
                        "kungfu_id": 10000 + index,
                        "kungfu": "kungfu-{}".format(index),
                        "game_score": 2000 + index,
                    }
                    for index in range(1, 4)
                ],
                "score_avg": score_avg,
            }

        return {
            "match_id": match_id,
            "match_time": 1_700_000_000 + match_id,
            "map": "竞技场",
            "duration": 120,
            "team1": team(True, "team1", 2002.0),
            "team2": team(False, "team2", 2102.0),
            "matched_orientations": orientations,
        }

    async def test_search_builds_directional_statistics_and_uses_match_count_as_total(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(items=[self._summary_item(42, ["forward"])])
        repo = _RecordingMatchupRepo(raw_result)
        request = self._request(
            team_a_kungfu_ids=[10080, 10001, 10080],
            team_b_kungfu_ids=[10242, 10002],
        )

        response = await JjcMatchupService(repo).search(request)

        expected_filters = {
            "start_time": 1_700_000_000,
            "end_time": 1_700_086_400,
            "score_min": 0,
            "score_max": 1_000_000,
            "team_a_kungfu_ids": [10001, 10080, 10080],
            "team_b_kungfu_ids": [10002, 10242],
            "page": 1,
            "page_size": 20,
        }
        self.assertEqual(repo.calls, [expected_filters])
        self.assertEqual(request["team_a_kungfu_ids"], [10080, 10001, 10080])
        self.assertEqual(set(response), {
            "normalized_filters", "statistics", "items", "page", "page_size", "total", "has_more",
        })
        self.assertEqual(response["normalized_filters"], expected_filters)
        self.assertEqual(response["page"], 1)
        self.assertEqual(response["page_size"], 20)
        self.assertEqual(response["total"], 3)
        self.assertFalse(response["has_more"])
        self.assertEqual(response["items"], raw_result["items"])
        self.assertEqual(response["statistics"], {
            "match_count": 3,
            "orientation_sample_count": 4,
            "bidirectional_match_count": 1,
            "team_a_wins": 3,
            "team_b_wins": 1,
            "team_a_win_rate": 75.0,
            "team_b_win_rate": 25.0,
            "missing_score_match_count": 2,
        })
        self._assert_has_no_conclusion_fields(response)

    async def test_search_rounds_directional_win_rates_half_up_to_one_decimal(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=400,
            bidirectional_match_count=0,
            team_a_wins=49,
            team_b_wins=351,
        )

        response = await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
            self._request(team_a_kungfu_ids=[10080]),
        )

        self.assertEqual(response["statistics"]["orientation_sample_count"], 400)
        self.assertEqual(response["statistics"]["team_a_win_rate"], 12.3)
        self.assertEqual(response["statistics"]["team_b_win_rate"], 87.8)

    async def test_search_returns_zero_direction_statistics_when_a_side_is_nonempty(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=0,
            bidirectional_match_count=0,
            team_a_wins=0,
            team_b_wins=0,
            missing_score_match_count=5,
        )

        response = await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
            self._request(team_b_kungfu_ids=[10080]),
        )

        self.assertEqual(response["total"], 0)
        self.assertFalse(response["has_more"])
        self.assertEqual(response["statistics"], {
            "match_count": 0,
            "orientation_sample_count": 0,
            "bidirectional_match_count": 0,
            "team_a_wins": 0,
            "team_b_wins": 0,
            "team_a_win_rate": None,
            "team_b_win_rate": None,
            "missing_score_match_count": 5,
        })

    async def test_search_returns_non_directional_null_wins_when_both_sides_are_empty(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=2,
            bidirectional_match_count=0,
            team_a_wins=0,
            team_b_wins=0,
            missing_score_match_count=1,
            items=[self._summary_item(40, [])],
        )

        response = await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(self._request())

        self.assertEqual(response["total"], 2)
        self.assertEqual(response["statistics"], {
            "match_count": 2,
            "orientation_sample_count": 0,
            "bidirectional_match_count": 0,
            "team_a_wins": None,
            "team_b_wins": None,
            "team_a_win_rate": None,
            "team_b_win_rate": None,
            "missing_score_match_count": 1,
        })

    async def test_search_rejects_inconsistent_raw_directional_statistics(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=3,
            bidirectional_match_count=1,
            team_a_wins=2,
            team_b_wins=1,
        )

        with self.assertRaisesRegex(ValueError, "raw matchup statistics are inconsistent"):
            await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
                self._request(team_a_kungfu_ids=[10080]),
            )

    async def test_search_rejects_directional_statistics_for_an_unoriented_query(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=1,
            bidirectional_match_count=1,
            team_a_wins=1,
            team_b_wins=1,
        )

        with self.assertRaisesRegex(ValueError, "raw matchup statistics are inconsistent"):
            await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(self._request())

    async def test_search_preserves_source_order_and_all_directional_orientation_forms(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        items = [
            self._summary_item(1, ["forward"]),
            self._summary_item(2, ["reverse"]),
            self._summary_item(3, ["forward", "reverse"]),
        ]
        raw_result = self._raw_result(
            match_count=3,
            bidirectional_match_count=1,
            team_a_wins=2,
            team_b_wins=2,
            items=items,
        )

        response = await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
            self._request(team_a_kungfu_ids=[10080]),
        )

        self.assertEqual(response["items"], items)
        self.assertEqual(
            [item["matched_orientations"] for item in response["items"]],
            [["forward"], ["reverse"], ["forward", "reverse"]],
        )
        self.assertEqual(response["items"][0]["team1"]["players"][0]["role_name"], "team1-role-1")
        self.assertEqual(response["items"][0]["team2"]["players"][0]["role_name"], "team2-role-1")

    async def test_search_rejects_empty_orientation_for_a_directional_query(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=1,
            bidirectional_match_count=0,
            team_a_wins=1,
            team_b_wins=0,
            items=[self._summary_item(4, [])],
        )

        with self.assertRaises(ValueError):
            await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
                self._request(team_a_kungfu_ids=[10080]),
            )

    async def test_search_uses_normalized_page_metadata_and_returns_false_for_a_legal_empty_page(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=40,
            bidirectional_match_count=0,
            team_a_wins=40,
            team_b_wins=0,
            items=[],
        )

        response = await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
            self._request(team_a_kungfu_ids=[10080], page=3, page_size=20),
        )

        self.assertEqual(response["page"], 3)
        self.assertEqual(response["page_size"], 20)
        self.assertEqual(response["items"], [])
        self.assertEqual(response["total"], 40)
        self.assertFalse(response["has_more"])

    async def test_search_sets_has_more_from_the_authoritative_match_count(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_result = self._raw_result(
            match_count=21,
            bidirectional_match_count=0,
            team_a_wins=21,
            team_b_wins=0,
            total=0,
        )

        response = await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
            self._request(team_a_kungfu_ids=[10080]),
        )

        self.assertEqual(response["total"], 21)
        self.assertTrue(response["has_more"])

    async def test_search_does_not_mutate_the_request_or_raw_repository_result(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        request = self._request(
            team_a_kungfu_ids=[10080, 10001],
            team_b_kungfu_ids=[10242],
        )
        raw_result = self._raw_result(
            items=[self._summary_item(42, ["forward"])],
        )
        request_before = copy.deepcopy(request)
        raw_before = copy.deepcopy(raw_result)

        await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(request)

        self.assertEqual(request, request_before)
        self.assertEqual(raw_result, raw_before)

    async def test_search_returns_only_a_detached_public_item_summary(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        raw_item = self._summary_item(42, ["forward"])
        internal_id = object()
        raw_item.update({
            "_id": internal_id,
            "active": True,
            "invalid_reason": "internal",
            "schema_version": 1,
            "source_cached_at": 123.4,
            "source_hash": "a" * 64,
            "projected_at": 123.4,
            "any_team_combo_keys": ["v1:1:10001"],
            "min_team_score_sum": 100,
            "max_team_score_sum": 200,
        })
        raw_item["team1"].update({
            "kungfu_ids": [10001, 10002, 10003],
            "combo_keys": ["v1:1:10001"],
            "score_sum": 6006,
            "score_count": 3,
            "score_complete": True,
        })
        raw_item["team1"]["players"][0]["score_source"] = "total_score"
        raw_result = self._raw_result(
            match_count=1,
            bidirectional_match_count=0,
            team_a_wins=1,
            team_b_wins=0,
            items=[raw_item],
        )

        response = await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
            self._request(team_a_kungfu_ids=[10080]),
        )

        self.assertEqual(set(response["items"][0]), {
            "match_id", "match_time", "map", "duration", "team1", "team2", "matched_orientations",
        })
        self.assertEqual(set(response["items"][0]["team1"]), {"won", "players", "score_avg"})
        self.assertEqual(
            set(response["items"][0]["team1"]["players"][0]),
            {"role_name", "server", "kungfu_id", "kungfu", "game_score"},
        )
        self.assertIsNot(response["items"][0], raw_item)
        self.assertNotIn("_id", response["items"][0])
        self.assertIs(raw_item["_id"], internal_id)

        response["items"][0]["team1"]["players"][0]["role_name"] = "changed"
        self.assertEqual(raw_item["team1"]["players"][0]["role_name"], "team1-role-1")

    async def test_search_rejects_missing_or_invalid_required_item_summary_fields(self) -> None:
        from src.services.jx3.jjc_matchup import JjcMatchupService

        invalid_mutations = (
            ("missing match_time", lambda item: item.pop("match_time")),
            ("non-positive match id", lambda item: item.__setitem__("match_id", 0)),
            ("non-string map", lambda item: item.__setitem__("map", 1)),
            ("negative duration", lambda item: item.__setitem__("duration", -1)),
            ("non-boolean won", lambda item: item["team1"].__setitem__("won", 1)),
            ("not three players", lambda item: item["team1"].__setitem__("players", [])),
            ("invalid kungfu id", lambda item: item["team1"]["players"][0].__setitem__("kungfu_id", True)),
            ("invalid game score", lambda item: item["team1"]["players"][0].__setitem__("game_score", None)),
            ("non-finite average", lambda item: item["team1"].__setitem__("score_avg", float("inf"))),
            ("non-string role", lambda item: item["team1"]["players"][0].__setitem__("role_name", None)),
        )

        for description, mutation in invalid_mutations:
            with self.subTest(description=description):
                item = self._summary_item(42, ["forward"])
                mutation(item)
                raw_result = self._raw_result(
                    match_count=1,
                    bidirectional_match_count=0,
                    team_a_wins=1,
                    team_b_wins=0,
                    items=[item],
                )
                with self.assertRaises(ValueError):
                    await JjcMatchupService(_RecordingMatchupRepo(raw_result)).search(
                        self._request(team_a_kungfu_ids=[10080]),
                    )


if __name__ == "__main__":
    unittest.main()
