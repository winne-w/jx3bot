"""Kungfu resolution has no JX3API transport or history fallback."""
import unittest
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.jx3.jjc_ranking import JjcRankingService

SERVER = "server-a"
NAME = "role-a"


def ranking(**overrides):
    person = {"server": SERVER, "roleName": NAME, "gameRoleId": "role-id", "zone": "zone-a"}
    person.update(overrides)
    return {"code": 0, "data": [{"personInfo": person}]}


class NoJx3apiKungfuFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.transport = AsyncMock(side_effect=AssertionError("JX3API must not be queried for kungfu"))
        self.service = JjcRankingService(
            arena_time_tag_url="", arena_ranking_url="", match_detail_url="",
            jjc_ranking_cache_duration=3600, kungfu_cache_duration=3600,
            current_season="season-a", current_season_start="2026-11-05",
            kungfu_healer_list=[], kungfu_dps_list=[], kungfu_pinyin_to_chinese={},
            tuilan_request=MagicMock(side_effect=AssertionError("use injected detail fixture")),
        )
        self.cache = SimpleNamespace(
            load_kungfu_cache=AsyncMock(return_value=None),
            load_kungfu_cache_raw=AsyncMock(return_value=None),
            save_kungfu_cache=AsyncMock(),
            get_kungfu_from_cached_match_detail_win_history=AsyncMock(return_value=None),
        )
        self.detail = MagicMock(return_value=None)
        self.warmup = AsyncMock()
        self.patches = [
            patch.object(JjcRankingService, "_cache", return_value=self.cache),
            patch.object(JjcRankingService, "_warmup_inspect_cache_from_kungfu_detail", new=self.warmup),
            patch("src.services.jx3.jjc_ranking.random_sleep", new=AsyncMock()),
            patch("src.services.jx3.jjc_ranking.get_kungfu_detail_by_role_info", new=self.detail),
            patch("src.infra.jx3api_get.get", new=self.transport),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_failure_matrix_never_queries_jx3api_or_overwrites_valid_cache(self):
        cases = [
            ("empty_kungfu", ranking(), {"kungfu": None}),
            ("empty_string", ranking(), {"kungfu": ""}),
            ("detail_exception", ranking(), RuntimeError("fixture-error")),
            ("ranking_failure", {"error": True}, None),
            ("not_ranked", {"code": 0, "data": []}, None),
            ("missing_role_id", ranking(gameRoleId=None), None),
            ("missing_zone", ranking(zone=None), None),
        ]
        for label, board, detail in cases:
            with self.subTest(label=label):
                self.transport.reset_mock()
                self.cache.save_kungfu_cache.reset_mock()
                self.detail.side_effect = detail if isinstance(detail, Exception) else None
                self.detail.return_value = detail if not isinstance(detail, Exception) else None
                result = await self.service.get_user_kungfu(SERVER, NAME, ranking_data=board)
                self.assertFalse(result["found"])
                self.assertIsNone(result["kungfu"])
                self.assertTrue(result.get("kungfu_unknown_reason") or result.get("reason"))
                self.transport.assert_not_awaited()
                self.cache.save_kungfu_cache.assert_not_awaited()

    async def test_failure_uses_local_current_season_win_and_preserves_source(self):
        local = {"found": True, "kungfu": "孤锋诀", "kungfu_id": 10015,
                 "kungfu_selected_source": "cached_match_detail_win_history",
                 "cached_match_detail_win_count": 3,
                 "cached_match_detail_latest_win_match_id": 42}
        self.cache.get_kungfu_from_cached_match_detail_win_history.return_value = local
        result = await self.service.get_user_kungfu(SERVER, NAME, ranking_data=ranking())
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["kungfu_selected_source"], "cached_match_detail_win_history")
        self.assertEqual(result["cached_match_detail_latest_win_match_id"], 42)
        self.cache.get_kungfu_from_cached_match_detail_win_history.assert_awaited_once_with(
            server=SERVER, name=NAME, season_start="2026-11-05", role_id="role-id")
        self.cache.save_kungfu_cache.assert_awaited_once()
        self.transport.assert_not_awaited()

    async def test_tuilan_success_preserves_details_and_prewarms(self):
        detail = {"kungfu": "孤锋诀", "kungfu_id": 10015, "weapon": {"name": "fixture"},
                  "teammates": [{"kungfu_id": 10081}], "history": [{"match_id": 42}]}
        self.detail.return_value = detail
        result = await self.service.get_user_kungfu(SERVER, NAME, ranking_data=ranking())
        for key, value in detail.items():
            self.assertEqual(result[key], value)
        self.assertTrue(result["found"])
        self.cache.save_kungfu_cache.assert_awaited_once()
        self.warmup.assert_awaited_once_with(server=SERVER, name=NAME, kungfu_detail=detail)
        self.cache.get_kungfu_from_cached_match_detail_win_history.assert_not_awaited()
        self.transport.assert_not_awaited()

    async def test_cache_hit_skips_tuilan_and_jx3api(self):
        self.cache.load_kungfu_cache.return_value = {"kungfu": "孤锋诀", "found": True}
        result = await self.service.get_user_kungfu(SERVER, NAME, ranking_data=ranking(), prefer_cache=True)
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.detail.assert_not_called()
        self.transport.assert_not_awaited()

    async def test_available_jx3api_history_is_ignored_when_local_has_no_result(self):
        self.transport.side_effect = None
        self.transport.return_value = {
            "msg": "success", "data": {"history": [{"won": True, "kungfu": "JX3API-only-fixture"}]}}
        result = await self.service.get_user_kungfu(SERVER, NAME, ranking_data={"code": 0, "data": []})
        self.assertFalse(result["found"])
        self.assertIsNone(result["kungfu"])
        self.cache.save_kungfu_cache.assert_not_awaited()
        self.transport.assert_not_awaited()

    async def test_ranking_exception_still_uses_local_without_jx3api(self):
        with patch.object(JjcRankingService, "query_jjc_ranking", new=AsyncMock(side_effect=RuntimeError("fixture"))):
            result = await self.service.get_user_kungfu(SERVER, NAME)
        self.assertFalse(result["found"])
        self.transport.assert_not_awaited()

    def test_service_has_no_jx3api_injection_or_legacy_history_method(self):
        names = {f.name for f in fields(JjcRankingService)}
        self.assertTrue(names.isdisjoint({"token", "ticket", "jjc_query_url", "defget_get"}))
        self.assertFalse(hasattr(JjcRankingService, "update_kungfu_cache"))
