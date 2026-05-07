import unittest
import sys
import types
from typing import Any, Dict, List

onebot_v11 = types.ModuleType("nonebot.adapters.onebot.v11")
onebot_v11.Bot = object
onebot_v11.Event = object
sys.modules.setdefault("nonebot.adapters", types.ModuleType("nonebot.adapters"))
sys.modules.setdefault("nonebot.adapters.onebot", types.ModuleType("nonebot.adapters.onebot"))
sys.modules.setdefault("nonebot.adapters.onebot.v11", onebot_v11)

from src.plugins.jx3bot_handlers import jjc_match_data_sync as handler


class FakeBot:
    def __init__(self) -> None:
        self.messages: List[str] = []

    async def send(self, event: Any, message: str) -> None:
        self.messages.append(message)


class FakeSyncService:
    def __init__(self) -> None:
        self.run_modes: List[str] = []
        self.run_limits: List[int] = []
        self.batch_calls: List[Dict[str, Any]] = []
        self.background_calls: List[Dict[str, Any]] = []

    async def run_once(self, mode: str = "incremental_or_full", limit: int = 3) -> Dict[str, Any]:
        self.run_modes.append(mode)
        self.run_limits.append(limit)
        return {
            "error": False,
            "recovered_leases": 1,
            "processed_roles": 2,
            "discovered_matches": 3,
            "saved_details": 4,
            "skipped_details": 5,
            "failed_roles": 0,
            "elapsed_seconds": 1.2,
        }

    async def run_until_idle(
        self,
        mode: str = "incremental_or_full",
        limit: int = 20,
        max_rounds: Any = None,
        max_seconds: int = 3600,
    ) -> Dict[str, Any]:
        self.batch_calls.append({
            "mode": mode,
            "limit": limit,
            "max_rounds": max_rounds,
            "max_seconds": max_seconds,
        })
        return {
            "error": False,
            "rounds": 2,
            "stopped_reason": "idle",
            "recovered_leases": 1,
            "processed_roles": 4,
            "discovered_matches": 3,
            "saved_details": 4,
            "skipped_details": 5,
            "failed_roles": 0,
            "elapsed_seconds": 2.4,
        }

    async def start_background_run(
        self,
        mode: str = "incremental_or_full",
        limit: int = 20,
        max_rounds: Any = None,
        max_seconds: int = 3600,
    ) -> Dict[str, Any]:
        self.background_calls.append({
            "mode": mode,
            "limit": limit,
            "max_rounds": max_rounds,
            "max_seconds": max_seconds,
        })
        return {"error": False}


class TestJjcMatchDataSyncHandler(unittest.IsolatedAsyncioTestCase):
    async def test_parse_add_args_supports_optional_key_values(self) -> None:
        server, name, kwargs = await handler._parse_add_args(
            "/jjc同步添加 梦江南 角色A global_role_id=gid role_id=rid zone=zone-a"
        )

        self.assertEqual(server, "梦江南")
        self.assertEqual(name, "角色A")
        self.assertEqual(kwargs["global_role_id"], "gid")
        self.assertEqual(kwargs["role_id"], "rid")
        self.assertEqual(kwargs["zone"], "zone-a")

    async def test_start_defaults_to_incremental_or_full(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始")

        self.assertEqual(svc.run_modes, ["incremental_or_full"])
        self.assertEqual(svc.run_limits, [3])
        self.assertIn("JJC 同步本轮结果", bot.messages[0])
        self.assertIn("处理角色: 2", bot.messages[0])

    async def test_start_passes_limit_to_run_once(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 incremental limit=50")

        self.assertEqual(svc.run_modes, ["incremental"])
        self.assertEqual(svc.run_limits, [50])

    async def test_start_runs_batch_when_rounds_set(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 full limit=50 rounds=20 minutes=10")

        self.assertEqual(svc.run_modes, [])
        self.assertEqual(svc.batch_calls[0], {
            "mode": "full",
            "limit": 50,
            "max_rounds": 20,
            "max_seconds": 600,
        })
        self.assertIn("JJC 同步批量结果", bot.messages[0])
        self.assertIn("执行轮数: 2", bot.messages[0])

    async def test_start_background_with_auto_rounds(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 limit=50 rounds=auto background")

        self.assertEqual(svc.background_calls[0], {
            "mode": "incremental_or_full",
            "limit": 50,
            "max_rounds": None,
            "max_seconds": 3600,
        })
        self.assertIn("JJC 后台批量同步已启动", bot.messages[0])
        self.assertIn("最大轮数: auto", bot.messages[0])
        self.assertIn("最长运行: 60分钟", bot.messages[0])

    async def test_start_rejects_invalid_mode(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 bad")

        self.assertEqual(svc.run_modes, [])
        self.assertIn("用法: /jjc同步开始", bot.messages[0])

    async def test_status_limits_recent_errors(self) -> None:
        class StatusService:
            async def status(self) -> Dict[str, Any]:
                return {
                    "error": False,
                    "paused": False,
                    "counts": {"pending": 1},
                    "background_running": False,
                    "last_background_summary": {
                        "stopped_reason": "idle",
                        "rounds": 2,
                        "processed_roles": 10,
                    },
                    "recent_errors": [
                        {"server": "梦江南", "name": f"角色{i}", "last_error": f"err{i}"}
                        for i in range(8)
                    ],
                }

        bot = FakeBot()

        await handler._cmd_status(bot, object(), StatusService())

        message = bot.messages[0]
        self.assertIn("待同步: 1", message)
        self.assertIn("角色4", message)
        self.assertNotIn("角色5", message)
        self.assertIn("最近后台批量：已停止(idle)，轮数 2，处理角色 10", message)


if __name__ == "__main__":
    unittest.main()
