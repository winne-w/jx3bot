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
        self.enqueue_calls: List[Dict[str, Any]] = []
        self.priority_calls: List[Dict[str, Any]] = []
        self.enqueue_result_overrides: Dict[str, Any] = {}

    async def enqueue_roles(
        self,
        mode: str = "incremental_or_full",
        limit: int = 10,
        source: str = "manual",
    ) -> Dict[str, Any]:
        self.enqueue_calls.append({"mode": mode, "limit": limit, "source": source})
        result = {
            "error": False,
            "mode": mode,
            "limit": limit,
            "enqueued_roles": 2,
            "recovered_leases": 1,
            "counts": {"queued": 5, "syncing": 1},
            "workers": [{"worker_id": "w1", "status": "idle", "online": True, "effective_status": "idle"}],
            "worker_running": True,
            "elapsed_seconds": 0.2,
        }
        result.update(self.enqueue_result_overrides)
        return result

    async def set_role_priority(
        self,
        server: str,
        name: str,
        priority: int,
        updated_by: Any = None,
    ) -> Dict[str, Any]:
        self.priority_calls.append({
            "server": server,
            "name": name,
            "priority": priority,
            "updated_by": updated_by,
        })
        return {"error": False, "message": f"角色 {server}/{name} 优先级已调整为 {priority}"}


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

        self.assertEqual(svc.enqueue_calls, [{"mode": "incremental_or_full", "limit": 10, "source": "qq_start"}])
        self.assertIn("JJC 同步已入队", bot.messages[0])
        self.assertIn("实际入队: 2", bot.messages[0])
        self.assertIn("worker: 有活跃 worker", bot.messages[0])

    async def test_start_passes_limit_to_enqueue(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 incremental limit=50")

        self.assertEqual(svc.enqueue_calls, [{"mode": "incremental", "limit": 50, "source": "qq_start"}])

    async def test_start_paused_still_reports_enqueued_roles(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()
        svc.enqueue_result_overrides = {
            "paused": True,
            "pause_reason": "更换 ticket",
            "enqueued_roles": 2,
        }

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 limit=2")

        self.assertIn("已暂停，角色已入队但 worker 暂不领取", bot.messages[0])
        self.assertIn("暂停原因: 更换 ticket", bot.messages[0])
        self.assertIn("实际入队: 2", bot.messages[0])

    async def test_start_ignores_legacy_rounds_after_enqueue(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 full limit=50 rounds=20 minutes=10")

        self.assertEqual(svc.enqueue_calls, [{"mode": "full", "limit": 50, "source": "qq_start"}])
        self.assertIn("JJC 同步已入队", bot.messages[0])
        self.assertIn("rounds/background 参数在队列模式下已忽略", bot.messages[0])

    async def test_start_background_with_auto_rounds(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 limit=50 rounds=auto background")

        self.assertEqual(svc.enqueue_calls, [{"mode": "incremental_or_full", "limit": 50, "source": "qq_start"}])
        self.assertIn("JJC 同步已入队", bot.messages[0])
        self.assertIn("rounds/background 参数在队列模式下已忽略", bot.messages[0])

    async def test_start_rejects_invalid_mode(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_start(bot, object(), svc, "/jjc同步开始 bad")

        self.assertEqual(svc.enqueue_calls, [])
        self.assertIn("用法: /jjc同步开始", bot.messages[0])

    async def test_status_limits_recent_errors(self) -> None:
        class StatusService:
            async def status(self) -> Dict[str, Any]:
                return {
                    "error": False,
                    "paused": False,
                    "counts": {"pending": 1, "queued": 2},
                    "pause_reason": "",
                    "workers": [
                        {
                            "worker_id": "worker-1",
                            "status": "syncing",
                            "effective_status": "syncing",
                            "online": True,
                            "current_server": "梦江南",
                            "current_name": "角色A",
                        }
                    ],
                    "worker_running": True,
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
        self.assertIn("全局状态：未暂停", message)
        self.assertIn("待同步: 1", message)
        self.assertIn("排队中: 2", message)
        self.assertIn("角色4", message)
        self.assertNotIn("角色5", message)
        self.assertIn("worker：有活跃 worker", message)
        self.assertIn("worker-1", message)

    async def test_status_uses_worker_online_flag_for_active_count(self) -> None:
        class StatusService:
            async def status(self) -> Dict[str, Any]:
                return {
                    "error": False,
                    "paused": False,
                    "counts": {"queued": 1},
                    "pause_reason": "",
                    "workers": [
                        {
                            "worker_id": "worker-old",
                            "status": "idle",
                            "effective_status": "offline",
                            "online": False,
                        }
                    ],
                    "worker_running": False,
                    "background_running": False,
                    "recent_errors": [],
                }

        bot = FakeBot()

        await handler._cmd_status(bot, object(), StatusService())

        message = bot.messages[0]
        self.assertIn("worker：无活跃 worker", message)
        self.assertIn("worker 可见: 1，活跃: 0", message)
        self.assertIn("worker-old: offline", message)

    async def test_add_rejects_invalid_queued_value(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()

        await handler._cmd_add(bot, object(), svc, "/jjc同步添加 梦江南 角色A queued=flase")

        self.assertEqual(bot.messages[0], "queued 必须是明确的布尔值，例如 queued=1 或 queued=0")

    async def test_priority_command_updates_service(self) -> None:
        bot = FakeBot()
        svc = FakeSyncService()
        event = types.SimpleNamespace(user_id=12345)

        await handler._cmd_priority(bot, event, svc, "/jjc同步优先级 梦江南 角色A 500")

        self.assertEqual(svc.priority_calls, [{
            "server": "梦江南",
            "name": "角色A",
            "priority": 500,
            "updated_by": "12345",
        }])
        self.assertIn("优先级已调整为 500", bot.messages[0])


if __name__ == "__main__":
    unittest.main()
