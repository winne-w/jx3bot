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

    async def run_once(self, mode: str = "incremental_or_full") -> Dict[str, Any]:
        self.run_modes.append(mode)
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
        self.assertIn("JJC 同步本轮结果", bot.messages[0])
        self.assertIn("处理角色: 2", bot.messages[0])

    async def test_start_rejects_invalid_mode(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 bad")

        self.assertEqual(svc.run_modes, [])
        self.assertEqual(bot.messages, ["用法: /jjc同步开始 [default|full|incremental]"])

    async def test_status_limits_recent_errors(self) -> None:
        class StatusService:
            async def status(self) -> Dict[str, Any]:
                return {
                    "error": False,
                    "paused": False,
                    "counts": {"pending": 1},
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


if __name__ == "__main__":
    unittest.main()
