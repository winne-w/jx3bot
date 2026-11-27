from __future__ import annotations

import asyncio
import types
import unittest
from typing import Any, Optional, Set
from unittest.mock import AsyncMock, patch

from tests.test_status_monitor_jobs_admin_notification import _FakeBot, _load_jobs


class _MemoryIdStore:
    def __init__(self, initial: Optional[dict[str, Set[Any]]] = None) -> None:
        self.store: dict[str, Set[Any]] = {k: set(v) for k, v in (initial or {}).items()}
        self.save_calls: list[tuple[str, Set[Any]]] = []

    async def load_id_set(self, cache_name: str) -> Set[Any]:
        return set(self.store.get(cache_name, set()))

    async def save_id_set(self, ids: Set[Any], cache_name: str) -> bool:
        snapshot = set(ids)
        self.store[cache_name] = snapshot
        self.save_calls.append((cache_name, snapshot))
        return True


class StatusMonitorScheduledJobsTests(unittest.TestCase):
    def test_resolve_daily_gte_hour_validates_bounds_and_types(self) -> None:
        module = _load_jobs()
        self.assertEqual(module._resolve_daily_gte_hour(0), 0)
        self.assertEqual(module._resolve_daily_gte_hour(9), 9)
        self.assertEqual(module._resolve_daily_gte_hour("23"), 23)
        self.assertEqual(module._resolve_daily_gte_hour(-1), 9)
        self.assertEqual(module._resolve_daily_gte_hour(24), 9)
        self.assertEqual(module._resolve_daily_gte_hour(True), 9)
        self.assertEqual(module._resolve_daily_gte_hour(False), 9)
        self.assertEqual(module._resolve_daily_gte_hour(9.5), 9)
        self.assertEqual(module._resolve_daily_gte_hour("invalid"), 9)
        self.assertEqual(module._resolve_daily_gte_hour(None), 9)

    def test_push_daily_gte_deduplicates_server_requests_and_caches_failures(self) -> None:
        bot = _FakeBot()
        module = _load_jobs(bots={"test": bot})
        module.BOT_INITIALIZED = True
        module.group_config_repo.load = AsyncMock(
            return_value={
                "1001": {"servers": "唯我独尊", "日常推送": True},
                "1002": {"servers": " 唯我独尊 ", "日常推送": True},
                "1003": {"servers": "唯我独尊", "日常推送": False},
                "1004": {"servers": "梦江南", "日常推送": True},
                "1005": {"servers": "梦江南", "日常推送": True},
                "1006": {"servers": ["唯我独尊"], "日常推送": True},
                "1007": {"servers": "   ", "日常推送": True},
                "1008": {"servers": "绝代天骄", "日常推送": True},
            }
        )
        module.send_group_msg = AsyncMock()

        async def _fake_get_gte(url: str, server: str) -> Any:
            if server == "梦江南":
                return None
            return {
                "data": {
                    "date": "2026-11-27",
                    "week": "五",
                    "war": f"{server}-大战",
                    "battle": "云湖天池",
                    "school": "宗门",
                    "rescue": "驰援",
                    "orecar": "阵营",
                    "luck": ["宠物A"],
                    "card": ["道具A"],
                }
            }

        module.get_gte_data = AsyncMock(side_effect=_fake_get_gte)

        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            asyncio.run(module.push_daily_gte())

        requested_servers = [call.kwargs["server"] for call in module.get_gte_data.await_args_list]
        self.assertEqual(requested_servers, ["唯我独尊", "梦江南", "绝代天骄"])
        sent_group_ids = [call.kwargs["group_id"] for call in module.send_group_msg.await_args_list]
        self.assertEqual(sent_group_ids, [1001, 1002, 1008])

    def test_check_records_defers_cache_advance_when_offline_and_recovers_on_reconnect(self) -> None:
        bot = _FakeBot()
        driver_state = types.SimpleNamespace(bots={})
        module = _load_jobs()
        module.BOT_INITIALIZED = True
        module.get_driver = lambda: driver_state
        store = _MemoryIdStore({"records_ids": {"1"}})
        module.load_id_set = store.load_id_set
        module.save_id_set = store.save_id_set
        module.previous_records_ids = set()
        module.group_config_repo.load = AsyncMock(return_value={"1001": {"技改推送": True}})
        module.send_group_msg = AsyncMock()
        module.get_records_data = AsyncMock(
            return_value={
                "data": [
                    {"id": "1", "title": "旧技改", "url": "https://a", "time": 1700000000},
                    {"id": "2", "title": "新技改", "url": "https://b", "time": 1700000100},
                ]
            }
        )

        # 断线轮询：不推送、不推进缓存
        asyncio.run(module.check_records())
        self.assertEqual(module.send_group_msg.await_count, 0)
        self.assertEqual(store.save_calls, [])
        self.assertEqual(module.previous_records_ids, {"1"})

        # 重连后轮询：补推并推进缓存
        driver_state.bots = {"test": bot}
        asyncio.run(module.check_records())
        self.assertEqual(module.send_group_msg.await_count, 1)
        self.assertIn("新技改", module.send_group_msg.await_args_list[0].kwargs["message"])
        self.assertEqual(module.previous_records_ids, {"1", "2"})
        self.assertEqual(len(store.save_calls), 1)
        self.assertEqual(store.save_calls[0], ("records_ids", {"1", "2"}))

    def test_check_news_defers_cache_advance_when_offline_and_recovers_on_reconnect(self) -> None:
        bot = _FakeBot()
        driver_state = types.SimpleNamespace(bots={})
        module = _load_jobs()
        module.BOT_INITIALIZED = True
        module.get_driver = lambda: driver_state
        store = _MemoryIdStore({"news_ids": {"10"}})
        module.load_id_set = store.load_id_set
        module.save_id_set = store.save_id_set
        module.previous_news_ids = set()
        module.group_config_repo.load = AsyncMock(return_value={"1001": {"新闻推送": True}})
        module.send_group_msg = AsyncMock()
        module.get_news_data = AsyncMock(
            return_value={
                "data": [
                    {"id": "10", "type": "新闻", "title": "旧新闻", "url": "https://a", "date": "2026-11-26"},
                    {"id": "11", "type": "新闻", "title": "新活动公告", "url": "https://b", "date": "2026-11-27"},
                ]
            }
        )

        asyncio.run(module.check_news())
        self.assertEqual(module.send_group_msg.await_count, 0)
        self.assertEqual(store.save_calls, [])
        self.assertEqual(module.previous_news_ids, {"10"})

        driver_state.bots = {"test": bot}
        asyncio.run(module.check_news())
        self.assertEqual(module.send_group_msg.await_count, 1)
        self.assertIn("新活动公告", module.send_group_msg.await_args_list[0].kwargs["message"])
        self.assertEqual(module.previous_news_ids, {"10", "11"})
        self.assertEqual(store.save_calls[-1], ("news_ids", {"10", "11"}))

    def test_check_event_codes_defers_only_for_active_codes_when_offline(self) -> None:
        bot = _FakeBot()
        driver_state = types.SimpleNamespace(bots={})
        module = _load_jobs()
        module.BOT_INITIALIZED = True
        module.get_driver = lambda: driver_state
        store = _MemoryIdStore({"event_codes_ids": {1}})
        module.load_id_set = store.load_id_set
        module.save_id_set = store.save_id_set
        module.previous_codes_ids = set()
        module.group_config_repo.load = AsyncMock(return_value={"1001": {"福利推送": True}})
        module.send_group_msg = AsyncMock()

        # 仅新增 status==0 的无效活动码：即使断线也直接推进缓存
        module.get_jx3box_data = AsyncMock(
            return_value={
                "data": {
                    "list": [
                        {"ID": 1, "status": 1, "title": "OLD", "desc": "old", "created_at": "2026-11-26T00:00:00Z"},
                        {"ID": 2, "status": 0, "title": "INACTIVE", "desc": "skip", "created_at": "2026-11-27T00:00:00Z"},
                    ]
                }
            }
        )
        asyncio.run(module.check_event_codes())
        self.assertEqual(module.send_group_msg.await_count, 0)
        self.assertEqual(module.previous_codes_ids, {1, 2})
        self.assertEqual(len(store.save_calls), 1)

        # 新增有效活动码且断线：暂缓推进缓存
        module.get_jx3box_data = AsyncMock(
            return_value={
                "data": {
                    "list": [
                        {"ID": 1, "status": 1, "title": "OLD", "desc": "old", "created_at": "2026-11-26T00:00:00Z"},
                        {"ID": 2, "status": 0, "title": "INACTIVE", "desc": "skip", "created_at": "2026-11-27T00:00:00Z"},
                        {"ID": 3, "status": 1, "title": "NEWCODE", "desc": "烟花", "created_at": "2026-11-27T10:00:00Z"},
                    ]
                }
            }
        )
        asyncio.run(module.check_event_codes())
        self.assertEqual(module.send_group_msg.await_count, 0)
        self.assertEqual(module.previous_codes_ids, {1, 2})
        self.assertEqual(len(store.save_calls), 1)

        # 重连后补推并推进缓存
        driver_state.bots = {"test": bot}
        asyncio.run(module.check_event_codes())
        self.assertEqual(module.send_group_msg.await_count, 1)
        self.assertIn("NEWCODE", module.send_group_msg.await_args_list[0].kwargs["message"])
        self.assertEqual(module.previous_codes_ids, {1, 2, 3})
        self.assertEqual(store.save_calls[-1], ("event_codes_ids", {1, 2, 3}))


if __name__ == "__main__":
    unittest.main()
