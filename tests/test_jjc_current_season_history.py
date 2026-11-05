import copy
import unittest
from unittest.mock import AsyncMock, MagicMock

from src.services.jx3.jjc_matchup import JjcMatchupService
from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches
from tests.test_jjc_ranking_inspect import (
    DirectJjcRankingInspectService, FakeJjcInspectRepo, FakeMatchHistoryClient,
    FakeWarmupInspectRepo, WarmupJjcRankingService,
)


START = 1793808000  # 2026-11-05 00:00:00 Asia/Shanghai
SEASON = "苍生铸世"


def match(match_id, timestamp, field="match_time", **extra):
    item = {"match_id": match_id, "pvpType": 3, field: timestamp}
    item.update(extra)
    return item


class _HistoryService(DirectJjcRankingInspectService):
    async def _resolve_role_identity(self, **kwargs):
        return {"global_role_id": "SK01-test", "global_id": "123", "identity_key": "global_id:123"}


def service_for(history, repo=None):
    return _HistoryService(
        ranking_service=MagicMock(), kungfu_cache_repo=MagicMock(),
        match_history_client=FakeMatchHistoryClient(history), match_detail_client=MagicMock(),
        cache_repo=repo or FakeJjcInspectRepo(), tuilan_request=MagicMock(),
        role_indicator_fetcher=MagicMock(), kungfu_pinyin_to_chinese={},
        current_season=SEASON, season_start_time=START, max_recent_matches=3,
    )


class CurrentSeasonHistoryTests(unittest.IsolatedAsyncioTestCase):
    def test_normalization_filters_before_limit_and_accepts_time_aliases(self):
        raw = [match(1, START - 1), {"match_id": 2, "pvpType": 3}]
        raw += [match(10 + i, START + i, key) for i, key in enumerate(
            ["match_time", "matchTime", "start_time", "startTime", "time"])]
        raw += [match(99, START + 100, pvpType=2)]
        before = copy.deepcopy(raw)
        rows = normalize_recent_matches(raw, kungfu_pinyin_to_chinese={},
                                        season_start_time=START, max_recent_matches=3)
        self.assertEqual([row["match_id"] for row in rows], [14, 13, 12])
        self.assertEqual(raw, before)
        boundary = normalize_recent_matches([match(3, START)], kungfu_pinyin_to_chinese={},
                                            season_start_time=START)
        self.assertEqual([row["match_id"] for row in boundary], [3])

    async def test_mixed_live_page_stops_at_previous_season(self):
        svc = service_for([match(3, START + 1), match(2, START), match(1, START - 1)])
        data = await svc.get_role_recent(server="梦江南", name="测试")
        self.assertEqual([row["match_id"] for row in data["recent_matches"]], [3, 2])
        self.assertEqual(data["pagination"], {"cursor": 0, "has_more": False, "next_cursor": None})
        saved = svc.cache_repo.saved_role_recent[0][2]["data"]
        self.assertEqual(saved["current_season"], SEASON)
        self.assertEqual(saved["season_start_time"], START)

    async def test_previous_season_only_later_page_is_empty_and_terminal(self):
        svc = service_for([match(3, START - 1), match(2, START - 2), match(1, START - 3)])
        data = await svc.get_role_recent(server="梦江南", name="测试", cursor=3)
        self.assertEqual(data["recent_matches"], [])
        self.assertEqual(data["pagination"], {"cursor": 3, "has_more": False, "next_cursor": None})
        self.assertEqual(svc.cache_repo.saved_role_recent, [])

    async def test_current_page_advances_by_raw_count_despite_non_3v3_rows(self):
        svc = service_for([match(3, START + 3), match(2, START + 2, pvpType=2), match(1, START + 1)])
        data = await svc.get_role_recent(server="梦江南", name="测试", cursor=3)
        self.assertEqual(len(data["recent_matches"]), 2)
        self.assertEqual(data["pagination"], {"cursor": 3, "has_more": True, "next_cursor": 6})

    async def test_old_unmarked_and_wrong_boundary_caches_are_not_reused(self):
        for metadata in [{}, {"current_season": "暗影千机", "season_start_time": START},
                         {"current_season": SEASON, "season_start_time": START - 604800}]:
            with self.subTest(metadata=metadata):
                repo = FakeJjcInspectRepo()
                repo.load_role_recent_result = {"cached_at": START + 100, "data": {
                    **metadata, "recent_matches": [match(1, START - 1)]}}
                svc = service_for([match(2, START)], repo)
                result = await svc.get_role_recent(server="梦江南", name="测试")
                self.assertFalse(result["cache"]["hit"])
                self.assertEqual([row["match_id"] for row in result["recent_matches"]], [2])
                self.assertEqual(len(svc.match_history_client.calls), 1)

    async def test_current_cache_is_filtered_before_hydration_without_upstream(self):
        repo = FakeJjcInspectRepo()
        repo.load_role_recent_result = {"cached_at": START + 100, "data": {
            "current_season": SEASON, "season_start_time": START,
            "recent_matches": [match(2, START), match(1, START - 1), {"match_id": 0}],
            "pagination": {"cursor": 0, "has_more": True, "next_cursor": 3}}}
        original = copy.deepcopy(repo.load_role_recent_result)
        svc = service_for([], repo)
        result = await svc.get_role_recent(server="梦江南", name="测试")
        self.assertTrue(result["cache"]["hit"])
        self.assertEqual([row["match_id"] for row in result["recent_matches"]], [2])
        self.assertFalse(result["pagination"]["has_more"])
        self.assertIsNone(result["pagination"]["next_cursor"])
        self.assertEqual(svc.match_history_client.calls, [])
        self.assertEqual(repo.load_role_recent_result, original)

    async def test_warmup_filters_and_marks_cache_and_stops_old_page(self):
        repo = FakeWarmupInspectRepo()
        svc = WarmupJjcRankingService(repo)
        object.__setattr__(svc, "current_season", SEASON)
        object.__setattr__(svc, "current_season_start", "2026-11-05")
        history = [match(i, START + i) for i in range(19, 0, -1)] + [match(0, START - 1)]
        await svc._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南", name="测试", kungfu_detail={"_cache_warmup": {
                "role_recent": {"raw_matches": history}}})
        data = repo.saved_role_recent[0][2]["data"]
        self.assertEqual(len(data["recent_matches"]), 19)
        self.assertEqual(data["current_season"], SEASON)
        self.assertEqual(data["season_start_time"], START)
        self.assertFalse(data["pagination"]["has_more"])

    async def test_warmup_does_not_end_paging_for_old_rows_beyond_first_page(self):
        repo = FakeWarmupInspectRepo()
        svc = WarmupJjcRankingService(repo)
        object.__setattr__(svc, "current_season", SEASON)
        object.__setattr__(svc, "current_season_start", "2026-11-05")
        history = [match(i, START + i) for i in range(30, 0, -1)] + [match(0, START - 1)]
        await svc._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南", name="测试", kungfu_detail={"_cache_warmup": {
                "role_recent": {"raw_matches": history}}})
        data = repo.saved_role_recent[0][2]["data"]
        self.assertEqual(len(data["recent_matches"]), 20)
        self.assertEqual(data["pagination"], {"cursor": 0, "has_more": True, "next_cursor": 20})


class CurrentSeasonMatchupTests(unittest.IsolatedAsyncioTestCase):
    def repo(self):
        return MagicMock(search_matchups=AsyncMock(return_value={"items": [], "statistics": {
            "match_count": 0, "bidirectional_match_count": 0, "team_a_wins": 0,
            "team_b_wins": 0, "missing_score_match_count": 0}}))

    def request(self, start, end):
        return {"start_time": start, "end_time": end, "score_min": 0, "score_max": 10000}

    async def test_cross_season_window_is_clipped_before_repository_counts_and_paging(self):
        repo = self.repo()
        result = await JjcMatchupService(repo, season_start_time=START).search(
            self.request(START - 86400, START + 86400))
        self.assertEqual(repo.search_matchups.await_args.args[0]["start_time"], START)
        self.assertEqual(result["normalized_filters"]["start_time"], START)

    async def test_previous_season_window_returns_empty_without_querying_repository(self):
        for end in [START - 1, START]:
            repo = self.repo()
            result = await JjcMatchupService(repo, season_start_time=START).search(
                self.request(START - 86400, end))
            self.assertEqual(result["items"], [])
            self.assertEqual(result["total"], 0)
            self.assertFalse(result["has_more"])
            self.assertEqual(result["statistics"]["match_count"], 0)
            repo.search_matchups.assert_not_awaited()
