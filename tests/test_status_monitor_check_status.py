from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from tests.test_status_monitor_jobs_admin_notification import _FakeBot, _load_jobs


class _MemoryCacheManager:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self.store: dict[str, Any] = dict(initial or {})

    async def load_cache(self, cache_name: str, default: Any = None) -> Any:
        return self.store.get(cache_name, default)

    async def save_cache(self, data: Any, cache_name: str) -> bool:
        self.store[cache_name] = data
        return True


class StatusMonitorCheckStatusTests(unittest.TestCase):
    def test_consecutive_runs_not_throttled_and_version_fetched_once(self) -> None:
        bot = _FakeBot()
        module = _load_jobs(bots={"test": bot})
        cache = _MemoryCacheManager(
            {
                "server_status": {"唯我独尊": 0},
                "status_history": {"唯我独尊": {"last_maintenance": 1700000000, "last_open": None}},
            }
        )
        module.CacheManager = cache
        module.previous_status = {}
        module.group_config_repo.load = AsyncMock(
            return_value={
                "1001": {"servers": "唯我独尊", "开服推送": True},
                "1002": {"servers": "唯我独尊", "开服推送": True},
                "1003": {"servers": "唯我独尊", "开服推送": False},
                "1004": {"servers": "梦江南", "开服推送": True},
            }
        )
        module.send_group_msg = AsyncMock()
        module.get_server_banben = AsyncMock(
            return_value={"data": [{"title": "剑网3 1.0.0.1234 版本更新公告"}]}
        )

        responses = [
            {
                "code": 200,
                "data": [{"zone": "电信五区", "server": "唯我独尊", "status": 0, "legacyStatus": 0, "time": 1700000000}],
            },
            {
                "code": 200,
                "data": [{"zone": "电信五区", "server": "唯我独尊", "status": 1, "legacyStatus": 1, "time": 1700000180}],
            },
        ]
        module.get_server_status = AsyncMock(side_effect=responses)

        async def _run() -> None:
            await module.check_status()
            await module.check_status()

        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            asyncio.run(_run())

        self.assertEqual(module.get_server_status.await_count, 2)
        self.assertEqual(module.get_server_banben.await_count, 1)
        self.assertEqual(module.send_group_msg.await_count, 2)
        sent_group_ids = [call.kwargs["group_id"] for call in module.send_group_msg.await_args_list]
        self.assertEqual(sent_group_ids, [1001, 1002])
        for call in module.send_group_msg.await_args_list:
            self.assertIn("唯我独尊「 已开服 」", call.kwargs["message"])
            self.assertIn("最新版本：1.0.0.1234", call.kwargs["message"])

    def test_no_matching_target_groups_skips_version_fetch(self) -> None:
        bot = _FakeBot()
        module = _load_jobs(bots={"test": bot})
        cache = _MemoryCacheManager({"server_status": {"唯我独尊": 0}, "status_history": {}})
        module.CacheManager = cache
        module.previous_status = {}
        module.group_config_repo.load = AsyncMock(
            return_value={
                "1001": {"servers": "梦江南", "开服推送": True},
                "1002": {"servers": "唯我独尊", "开服推送": False},
            }
        )
        module.send_group_msg = AsyncMock()
        module.get_server_banben = AsyncMock()
        module.get_server_status = AsyncMock(
            return_value={
                "code": 200,
                "data": [{"zone": "电信五区", "server": "唯我独尊", "status": 1, "legacyStatus": 1, "time": 1700000180}],
            }
        )

        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            asyncio.run(module.check_status())

        self.assertEqual(module.get_server_banben.await_count, 0)
        self.assertEqual(module.send_group_msg.await_count, 0)

    def test_version_fetch_error_degrades_gracefully_and_ignores_invalid_server_config(self) -> None:
        bot = _FakeBot()
        module = _load_jobs(bots={"test": bot})
        cache = _MemoryCacheManager({"server_status": {"唯我独尊": 0}, "status_history": {}})
        module.CacheManager = cache
        module.previous_status = {}
        module.group_config_repo.load = AsyncMock(
            return_value={
                "1001": {"servers": ["唯我独尊"], "开服推送": True},
                "1002": {"servers": "唯我独尊", "开服推送": True},
            }
        )
        module.send_group_msg = AsyncMock()
        module.get_server_banben = AsyncMock(side_effect=RuntimeError("announce timeout"))
        module.get_server_status = AsyncMock(
            return_value={
                "code": 200,
                "data": [{"zone": "电信五区", "server": "唯我独尊", "status": 1, "legacyStatus": 1, "time": 1700000180}],
            }
        )

        with patch.object(module.asyncio, "sleep", new=AsyncMock()):
            asyncio.run(module.check_status())

        self.assertEqual(module.get_server_banben.await_count, 1)
        self.assertEqual(module.send_group_msg.await_count, 1)
        sent = module.send_group_msg.await_args_list[0].kwargs
        self.assertEqual(sent["group_id"], 1002)
        self.assertIn("唯我独尊「 已开服 」", sent["message"])
        self.assertNotIn("最新版本：", sent["message"])


if __name__ == "__main__":
    unittest.main()
