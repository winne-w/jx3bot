import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.jx3.jjc_ranking import JjcRankingService


class JjcRankingExplicitTagTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = JjcRankingService(
            token="", ticket="", jjc_query_url="", arena_time_tag_url="",
            arena_ranking_url="", match_detail_url="",
            jjc_ranking_cache_duration=3600, kungfu_cache_duration=3600,
            current_season="S12", current_season_start="2026-04-24",
            kungfu_healer_list=[], kungfu_dps_list=[], kungfu_pinyin_to_chinese={},
            tuilan_request=MagicMock(), defget_get=AsyncMock(),
        )
        self.api = MagicMock()
        self.api.get_arena_time_tag.return_value = {
            "code": 0, "data": {"defaultWeek": 41, "tags": [40, 41, 99]},
        }
        self.api.get_arena_ranking.return_value = {"code": 0, "data": [{"rank": 1}]}
        self.cache = MagicMock()
        self.cache.load_ranking_cache = AsyncMock(return_value=None)
        self.cache.save_ranking_cache = AsyncMock()

        async def run_api_call(func, *args, **kwargs):
            return func(*args, **kwargs)

        for name, patcher in [
            ("api_factory", patch.object(JjcRankingService, "_api", return_value=self.api)),
            ("cache_factory", patch.object(JjcRankingService, "_cache", return_value=self.cache)),
            ("sleep", patch("src.services.jx3.jjc_ranking.fixed_sleep", new=AsyncMock())),
            ("clock", patch("src.services.jx3.jjc_ranking.time.time", return_value=1234567890)),
            ("thread_call", patch("src.services.jx3.jjc_ranking.asyncio.to_thread", new=run_api_call)),
        ]:
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    async def test_default_cache_hit_returns_existing_data_without_api(self):
        cached = {"code": 0, "defaultWeek": 39, "cache_time": 100, "data": []}
        self.cache.load_ranking_cache.return_value = cached

        self.assertEqual(await self.service.query_jjc_ranking(), cached)

        self.api_factory.assert_not_called()
        self.cache.save_ranking_cache.assert_not_awaited()
        self.sleep.assert_not_awaited()

    async def test_default_cache_miss_uses_default_week_instead_of_largest_tag(self):
        result = await self.service.query_jjc_ranking()

        self.assertEqual(result["defaultWeek"], 41)
        self.api.get_arena_time_tag.assert_called_once_with()
        self.api.get_arena_ranking.assert_called_once_with(41)
        self.cache.load_ranking_cache.assert_awaited_once_with()
        self.cache.save_ranking_cache.assert_awaited_once_with(result)
        self.sleep.assert_awaited_once_with(5.45)

    async def test_explicit_tag_bypasses_other_week_cache_and_time_tag(self):
        self.cache.load_ranking_cache.return_value = {"code": 0, "defaultWeek": 99, "data": []}

        result = await self.service.query_jjc_ranking(tag=40)

        self.assertEqual(result, {
            "code": 0, "data": [{"rank": 1}], "defaultWeek": 40, "cache_time": 1234567890,
        })
        self.api.get_arena_ranking.assert_called_once_with(40)
        self.api.get_arena_time_tag.assert_not_called()
        self.cache_factory.assert_not_called()
        self.cache.load_ranking_cache.assert_not_awaited()
        self.cache.save_ranking_cache.assert_not_awaited()
        self.sleep.assert_not_awaited()

    async def test_explicit_tag_errors_do_not_fall_back_or_write_default_cache(self):
        for response, message in [
            ({"error": "network unavailable"}, "获取竞技场排行榜失败: network unavailable"),
            ({"code": -1, "msg": "no data found"}, "获取竞技场排行榜失败: no data found"),
        ]:
            with self.subTest(response=response):
                self.api.get_arena_ranking.return_value = response
                self.api.get_arena_ranking.reset_mock()

                result = await self.service.query_jjc_ranking(tag=40)

                self.assertEqual(result, {"error": True, "message": message})
                self.api.get_arena_ranking.assert_called_once_with(40)
                self.api.get_arena_time_tag.assert_not_called()
                self.cache_factory.assert_not_called()
                self.sleep.assert_not_awaited()

    async def test_explicit_tag_exception_returns_error_without_fallback(self):
        self.api.get_arena_ranking.side_effect = RuntimeError("offline")

        result = await self.service.query_jjc_ranking(tag=40)

        self.assertEqual(result, {"error": True, "message": "查询竞技场排行榜失败: offline"})
        self.api.get_arena_ranking.assert_called_once_with(40)
        self.api.get_arena_time_tag.assert_not_called()
        self.cache_factory.assert_not_called()
        self.sleep.assert_not_awaited()

    async def test_invalid_explicit_tag_rejected_before_cache_or_external_requests(self):
        for tag in (0, -1, True, False, "40", 40.0, "", [], {}):
            with self.subTest(tag=tag):
                result = await self.service.query_jjc_ranking(tag=tag)

                self.assertTrue(result["error"])
                self.assertIn("正整数", result["message"])
                self.api_factory.assert_not_called()
                self.cache_factory.assert_not_called()
                self.sleep.assert_not_awaited()

    async def test_default_time_tag_failure_does_not_query_ranking(self):
        for response, message in [
            ({"error": "offline"}, "获取时间标签失败: offline"),
            ({"code": 1, "msg": "denied"}, "获取时间标签失败: denied"),
            ({"code": 0, "data": {}}, "获取时间标签失败: 缺少 defaultWeek 参数: {}"),
        ]:
            with self.subTest(response=response):
                self.api.get_arena_time_tag.return_value = response

                result = await self.service.query_jjc_ranking()

                self.assertEqual(result, {"error": True, "message": message})
                self.api.get_arena_ranking.assert_not_called()
                self.cache.save_ranking_cache.assert_not_awaited()
