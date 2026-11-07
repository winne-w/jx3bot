from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from src.plugins.jx3bot_handlers.jjc_ranking import register


class RecordingMatcher:
    def handle(self):
        def decorator(callback):
            self.callback = callback
            return callback

        return decorator


class JjcRankingCommandTagTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.matcher = RecordingMatcher()
        self.bot = SimpleNamespace(send=AsyncMock())
        self.ranking = {
            "code": 0,
            "data": [{"role_id": "test-role"}],
            "defaultWeek": 40,
            "cache_time": 123.0,
        }
        self.stats = {"天策": {"count": 1}}
        self.query = AsyncMock(return_value=self.ranking)
        self.week = Mock(return_value="第3周")
        self.kungfu = AsyncMock(return_value={
            "kungfu_statistics": self.stats,
            "ranking_kungfu_lines": ["测试角色：天策"],
            "missing_kungfu_lines": [],
        })
        self.save = Mock()
        self.split = AsyncMock()
        self.combined = AsyncMock()
        register(
            self.matcher,
            query_jjc_ranking=self.query,
            calculate_season_week_info=self.week,
            get_ranking_kungfu_data=self.kungfu,
            save_ranking_stats=self.save,
            generate_split_ranking_images=self.split,
            generate_combined_ranking_image=self.combined,
        )

    async def invoke(self, message: str):
        event = SimpleNamespace(get_plaintext=lambda: message)
        await self.matcher.callback(self.bot, event)
        return event

    async def test_explicit_tag_reaches_query_week_archive_and_image(self) -> None:
        for alias in ("竞技排名", "竞技排名统计", "竞排名"):
            with self.subTest(alias=alias):
                self.query.reset_mock()
                event = await self.invoke(alias + " tag=40")
                self.query.assert_awaited_once_with(tag=40)
                self.week.assert_called_with(40, 123.0)
                self.kungfu.assert_awaited_with(
                    ranking_data=self.ranking, use_cached_kungfu=False
                )
                self.save.assert_called_with(self.ranking, self.stats, "第3周")
                self.combined.assert_awaited_with(
                    self.bot, event, self.stats, "第3周", False
                )
        self.split.assert_not_awaited()

    async def test_tag_preserves_existing_options_in_any_order(self) -> None:
        event = await self.invoke("竞排名 缓存心法 拆分 tag=40 DEBUG 橙武占比")
        self.query.assert_awaited_once_with(tag=40)
        self.kungfu.assert_awaited_once_with(
            ranking_data=self.ranking, use_cached_kungfu=True
        )
        self.split.assert_awaited_once_with(
            self.bot, event, self.stats, "第3周", True
        )
        self.combined.assert_not_awaited()
        self.assertTrue(any("测试角色：天策" in call.args[1] for call in self.bot.send.await_args_list))

    async def test_sync_request_context_is_forwarded_without_cache_feature_flags(self):
        self.kungfu.return_value["_sync_request"] = {"order": "request", "until": 14}
        await self.invoke("竞技排名统计")
        self.assertEqual(self.save.call_args.kwargs.get("payload"), self.kungfu.return_value)

    async def test_omitted_tag_keeps_no_argument_query(self) -> None:
        await self.invoke("竞技排名统计 缓存心法")
        self.query.assert_awaited_once_with()

    async def test_invalid_tags_reject_before_any_business_work(self) -> None:
        for value in ("", " 缓存心法", "abc", "-1", "0", "1.5", "+1", "40 tag=41", "４０"):
            with self.subTest(value=value):
                self.bot.send.reset_mock()
                await self.invoke("竞技排名 tag=" + value)
                self.query.assert_not_awaited()
                self.kungfu.assert_not_awaited()
                self.week.assert_not_called()
                self.save.assert_not_called()
                self.combined.assert_not_awaited()
                self.split.assert_not_awaited()
                self.bot.send.assert_awaited_once()
                self.assertIn("正整数", self.bot.send.await_args.args[1])
                self.assertIn("tag=40", self.bot.send.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
