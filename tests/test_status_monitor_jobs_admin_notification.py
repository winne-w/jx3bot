from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock


class _FakeScheduler:
    def scheduled_job(self, *args: Any, **kwargs: Any) -> Any:
        def decorator(func: Any) -> Any:
            return func

        return decorator


class _FakeBot:
    def __init__(self) -> None:
        self.send_private_msg = AsyncMock()
        self.send_group_msg = AsyncMock()


class _FakeLogger:
    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass


def _load_jobs(
    *,
    admin_qq: list[int] | None = None,
    bots: Dict[str, Any] | None = None,
) -> Any:
    module_names = [
        "src",
        "src.plugins",
        "src.plugins.status_monitor",
        "src.infra",
        "src.infra.jx3api_compat",
        "config",
        "nonebot",
        "nonebot.adapters",
        "nonebot.adapters.onebot",
        "nonebot.adapters.onebot.v11",
        "nonebot_plugin_apscheduler",
        "src.plugins.status_monitor.notify",
        "src.plugins.status_monitor.storage",
        "src.services.jx3.jjc_peak_score_ranking",
        "src.services.jx3.singletons",
        "src.renderers.jx3.image",
        "src.renderers.jx3.jjc_ranking",
        "src.plugins.status_monitor.jobs_under_test",
    ]
    originals: Dict[str, Any] = {name: sys.modules.get(name) for name in module_names}

    config_mod = types.ModuleType("config")
    config_mod.ADMIN_QQ = admin_qq if admin_qq is not None else [10001, 10002]
    config_mod.CURRENT_SEASON = "test-season"
    sys.modules["config"] = config_mod

    src_mod = types.ModuleType("src")
    src_mod.__path__ = [str(Path(__file__).resolve().parents[1] / "src")]
    plugins_mod = types.ModuleType("src.plugins")
    plugins_mod.__path__ = []
    status_monitor_mod = types.ModuleType("src.plugins.status_monitor")
    status_monitor_mod.__path__ = []
    sys.modules["src"] = src_mod
    sys.modules["src.plugins"] = plugins_mod
    sys.modules["src.plugins.status_monitor"] = status_monitor_mod

    driver = types.SimpleNamespace(bots=bots if bots is not None else {})
    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.get_driver = lambda: driver
    nonebot_mod.logger = _FakeLogger()
    sys.modules["nonebot"] = nonebot_mod

    adapters_mod = types.ModuleType("nonebot.adapters")
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.MessageSegment = types.SimpleNamespace(image=lambda payload: payload)
    sys.modules["nonebot.adapters"] = adapters_mod
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

    scheduler_mod = types.ModuleType("nonebot_plugin_apscheduler")
    scheduler_mod.scheduler = _FakeScheduler()
    sys.modules["nonebot_plugin_apscheduler"] = scheduler_mod

    notify_mod = types.ModuleType("src.plugins.status_monitor.notify")
    notify_mod.get_NapCat_data = AsyncMock()
    notify_mod.send_email_via_163 = lambda content: True
    sys.modules["src.plugins.status_monitor.notify"] = notify_mod

    storage_mod = types.ModuleType("src.plugins.status_monitor.storage")
    storage_mod.CacheManager = object
    storage_mod.load_id_set = lambda key: set()
    storage_mod.save_id_set = lambda key, value: None
    sys.modules["src.plugins.status_monitor.storage"] = storage_mod

    peak_mod = types.ModuleType("src.services.jx3.jjc_peak_score_ranking")
    peak_mod.JjcPeakScoreRankingService = type("JjcPeakScoreRankingService", (), {})
    sys.modules["src.services.jx3.jjc_peak_score_ranking"] = peak_mod

    singletons_mod = types.ModuleType("src.services.jx3.singletons")
    singletons_mod.env = object()
    singletons_mod.group_config_repo = types.SimpleNamespace(load=AsyncMock(return_value={}))
    singletons_mod.jjc_ranking_service = types.SimpleNamespace()
    sys.modules["src.services.jx3.singletons"] = singletons_mod

    image_mod = types.ModuleType("src.renderers.jx3.image")
    image_mod.render_template_image = AsyncMock()
    sys.modules["src.renderers.jx3.image"] = image_mod

    ranking_mod = types.ModuleType("src.renderers.jx3.jjc_ranking")
    ranking_mod.render_combined_ranking_image = AsyncMock()
    sys.modules["src.renderers.jx3.jjc_ranking"] = ranking_mod

    module_path = Path(__file__).resolve().parents[1] / "src" / "plugins" / "status_monitor" / "jobs.py"
    spec = importlib.util.spec_from_file_location(
        "src.plugins.status_monitor.jobs_under_test", str(module_path)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load status_monitor jobs")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


class StatusMonitorJobsAdminNotificationTests(unittest.TestCase):
    @staticmethod
    def _prepare_ranking_job(
        module: Any,
        *,
        ranking_result: Any = None,
        ranking_data: Any = None,
        payload: Any = None,
    ) -> tuple[_FakeBot, AsyncMock]:
        bot = _FakeBot()
        module.BOT_INITIALIZED = True
        module.get_driver = lambda: types.SimpleNamespace(bots={"test": bot})
        module.group_config_repo.load = AsyncMock(
            return_value={"123": {"竞技排名推送": True}}
        )
        module.jjc_ranking_service = types.SimpleNamespace(
            query_jjc_ranking=AsyncMock(return_value=ranking_result),
            calculate_season_week_info=lambda default_week, cache_time: "第1周",
            get_ranking_kungfu_data=AsyncMock(return_value=ranking_data),
            save_ranking_stats=lambda **kwargs: None,
        )
        module.render_combined_ranking_image = AsyncMock(return_value=payload)
        notify = AsyncMock()
        module.notify_jjc_ranking_failure = notify
        return bot, notify

    def test_notify_jjc_ranking_failure_sends_every_admin(self) -> None:
        module = _load_jobs(admin_qq=[101, 202])
        bot = _FakeBot()

        asyncio.run(module.notify_jjc_ranking_failure(bot, "排行榜接口失败：超时"))

        self.assertEqual(
            bot.send_private_msg.await_args_list,
            [
                unittest.mock.call(user_id=101, message="竞技排名定时任务统计失败：排行榜接口失败：超时"),
                unittest.mock.call(user_id=202, message="竞技排名定时任务统计失败：排行榜接口失败：超时"),
            ],
        )

    def test_notify_jjc_ranking_failure_continues_after_one_admin_send_fails(self) -> None:
        module = _load_jobs(admin_qq=[101, 202])
        bot = _FakeBot()
        bot.send_private_msg.side_effect = [RuntimeError("blocked"), None]

        asyncio.run(module.notify_jjc_ranking_failure(bot, "统计为空"))

        self.assertEqual(bot.send_private_msg.await_count, 2)
        self.assertEqual(bot.send_private_msg.await_args_list[1], unittest.mock.call(
            user_id=202,
            message="竞技排名定时任务统计失败：统计为空",
        ))

    def test_push_daily_jjc_ranking_notifies_every_statistics_failure_exit(self) -> None:
        successful_ranking = {"code": 0, "defaultWeek": 1, "cache_time": 1}
        successful_data = {"kungfu_statistics": {"dps": {}}}
        cases = [
            ("排行榜为空", None, None, None, "返回为空"),
            ("排行榜业务错误", {"error": True, "message": "上游超时"}, None, None, "上游超时"),
            ("排行榜错误码", {"code": 500}, None, None, "500"),
            ("心法数据为空", successful_ranking, None, None, "心法统计数据失败"),
            (
                "心法业务错误",
                successful_ranking,
                {"error": True, "message": "心法上游超时"},
                None,
                "心法上游超时",
            ),
            ("统计为空", successful_ranking, {"kungfu_statistics": {}}, None, "心法统计数据为空"),
            ("渲染为空", successful_ranking, successful_data, None, "渲染竞技场统计图失败"),
        ]

        for name, ranking_result, ranking_data, payload, expected_detail in cases:
            with self.subTest(name=name):
                module = _load_jobs()
                _, notify = self._prepare_ranking_job(
                    module,
                    ranking_result=ranking_result,
                    ranking_data=ranking_data,
                    payload=payload,
                )

                asyncio.run(module.push_daily_jjc_ranking())

                notify.assert_awaited_once()
                self.assertIn(expected_detail, notify.await_args.args[1])

    def test_push_daily_jjc_ranking_notifies_unexpected_exception(self) -> None:
        module = _load_jobs()
        _, notify = self._prepare_ranking_job(
            module,
            ranking_result={"code": 0, "defaultWeek": 1},
            ranking_data={"kungfu_statistics": {"dps": {}}},
        )
        module.group_config_repo.load = AsyncMock(side_effect=RuntimeError("Mongo不可用"))

        asyncio.run(module.push_daily_jjc_ranking())

        notify.assert_awaited_once()
        self.assertIn("Mongo不可用", notify.await_args.args[1])

    def test_push_daily_jjc_ranking_does_not_notify_when_no_bot_or_target_group(self) -> None:
        for online in (False, True):
            with self.subTest(online=online):
                module = _load_jobs()
                bot, notify = self._prepare_ranking_job(
                    module,
                    ranking_result={"code": 0, "defaultWeek": 1},
                    ranking_data={"kungfu_statistics": {"dps": {}}},
                )
                module.get_driver = lambda: types.SimpleNamespace(
                    bots={"test": bot} if online else {}
                )
                module.group_config_repo.load.return_value = {"123": {"竞技排名推送": False}}

                asyncio.run(module.push_daily_jjc_ranking())

                notify.assert_not_awaited()

    def test_push_daily_jjc_ranking_sends_missing_kungfu_only_to_admins_once(self) -> None:
        module = _load_jobs(admin_qq=[101, 202])
        missing_lines = [
            "1. 梦江南 角色A - id:1001",
            "2. 唯满侠 角色B - id:1002",
        ]
        bot, notify = self._prepare_ranking_job(
            module,
            ranking_result={"code": 0, "defaultWeek": 1, "cache_time": 1},
            ranking_data={
                "kungfu_statistics": {"dps": {}},
                "missing_kungfu_lines": missing_lines,
            },
            payload={
                "image_bytes": b"png-bytes",
                "scope_desc": "前200、前100、前50",
                "total_valid_data": 198,
                "processed_label": "前200名",
            },
        )
        module.group_config_repo.load = AsyncMock(
            return_value={
                "123": {"竞技排名推送": True},
                "456": {"竞技排名推送": True},
            }
        )
        bot.get_group_list = AsyncMock(return_value=[{"group_id": 123}, {"group_id": 456}])

        with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()) as sleep_mock:
            asyncio.run(module.push_daily_jjc_ranking())

        notify.assert_not_awaited()
        expected_summary = (
            "⏰ 每日03:00/21:00竞技排名推送（第1周）\n"
            "统计范围：前200、前100、前50\n"
            "统计完成！共处理 198 条有效数据（前200名）"
        )
        self.assertEqual(
            bot.send_group_msg.await_args_list,
            [
                unittest.mock.call(group_id=123, message=b"png-bytes"),
                unittest.mock.call(group_id=123, message=expected_summary),
                unittest.mock.call(group_id=456, message=b"png-bytes"),
                unittest.mock.call(group_id=456, message=expected_summary),
            ],
        )

        expected_private_msg = (
            "【每日竞技排名定时任务（第1周）】未查询到心法的角色（共2人，第1-2名）\n"
            "1. 梦江南 角色A - id:1001\n"
            "2. 唯满侠 角色B - id:1002"
        )
        self.assertEqual(
            bot.send_private_msg.await_args_list,
            [
                unittest.mock.call(user_id=101, message=expected_private_msg),
                unittest.mock.call(user_id=202, message=expected_private_msg),
            ],
        )
        # 2 个群各 sleep 1 次 + 2 个管理员之间 sleep 1 次（最后 1 条私聊后不再 sleep）
        self.assertEqual(sleep_mock.await_count, 3)

    def test_notify_jjc_ranking_missing_kungfu_chunks_and_continues_after_admin_error(self) -> None:
        module = _load_jobs(admin_qq=[101, 202])
        bot = _FakeBot()
        bot.send_private_msg.side_effect = [RuntimeError("blocked"), None, None]
        missing_lines = [f"{i}. 梦江南 角色{i} - id:{i}" for i in range(1, 102)]

        with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()) as sleep_mock:
            asyncio.run(module.notify_jjc_ranking_missing_kungfu(bot, missing_lines, week_info="第3周"))

        self.assertEqual(bot.send_private_msg.await_count, 3)
        self.assertEqual(bot.send_private_msg.await_args_list[0].kwargs["user_id"], 101)
        self.assertEqual(bot.send_private_msg.await_args_list[1].kwargs["user_id"], 202)
        self.assertIn(
            "【每日竞技排名定时任务（第3周）】未查询到心法的角色（共101人，第1-100名）",
            bot.send_private_msg.await_args_list[1].kwargs["message"],
        )
        self.assertEqual(bot.send_private_msg.await_args_list[2].kwargs["user_id"], 202)
        self.assertIn(
            "【每日竞技排名定时任务（第3周）】未查询到心法的角色（共101人，第101-101名）",
            bot.send_private_msg.await_args_list[2].kwargs["message"],
        )
        # 管理员 202 的第 1 片与第 2 片之间 sleep 1 次；最后一片后不 sleep
        self.assertEqual(sleep_mock.await_count, 1)

    def test_push_daily_jjc_ranking_sends_missing_kungfu_to_admins_when_no_target_groups(self) -> None:
        module = _load_jobs(admin_qq=[101])
        bot, notify = self._prepare_ranking_job(
            module,
            ranking_result={"code": 0, "defaultWeek": 1, "cache_time": 1},
            ranking_data={
                "kungfu_statistics": {"dps": {}},
                "missing_kungfu_lines": ["1. 梦江南 角色A - id:1001"],
            },
        )
        module.group_config_repo.load = AsyncMock(return_value={"123": {"竞技排名推送": False}})

        with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()) as sleep_mock:
            asyncio.run(module.push_daily_jjc_ranking())

        notify.assert_not_awaited()
        bot.send_group_msg.assert_not_awaited()
        bot.send_private_msg.assert_awaited_once_with(
            user_id=101,
            message="【每日竞技排名定时任务（第1周）】未查询到心法的角色（共1人，第1-1名）\n1. 梦江南 角色A - id:1001",
        )
        sleep_mock.assert_not_awaited()

    def test_push_daily_jjc_ranking_skips_private_msg_when_missing_kungfu_empty_or_none(self) -> None:
        for missing_value in ([], None):
            with self.subTest(missing_value=missing_value):
                module = _load_jobs(admin_qq=[101])
                bot, notify = self._prepare_ranking_job(
                    module,
                    ranking_result={"code": 0, "defaultWeek": 1, "cache_time": 1},
                    ranking_data={
                        "kungfu_statistics": {"dps": {}},
                        "missing_kungfu_lines": missing_value,
                    },
                    payload={
                        "image_bytes": b"png-bytes",
                        "scope_desc": "前200、前100、前50",
                        "total_valid_data": 200,
                        "processed_label": "前200名",
                    },
                )
                bot.get_group_list = AsyncMock(return_value=[{"group_id": 123}])

                with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()):
                    asyncio.run(module.push_daily_jjc_ranking())

                notify.assert_not_awaited()
                self.assertEqual(bot.send_group_msg.await_count, 2)
                bot.send_private_msg.assert_not_awaited()

    def test_push_daily_jjc_ranking_still_sends_missing_kungfu_when_render_fails_or_group_fails(self) -> None:
        with self.subTest(case="render_fails"):
            module = _load_jobs(admin_qq=[101])
            bot, notify = self._prepare_ranking_job(
                module,
                ranking_result={"code": 0, "defaultWeek": 1, "cache_time": 1},
                ranking_data={
                    "kungfu_statistics": {"dps": {}},
                    "missing_kungfu_lines": ["1. 梦江南 角色A - id:1001"],
                },
                payload=None,
            )

            with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()):
                asyncio.run(module.push_daily_jjc_ranking())

            notify.assert_awaited_once()
            bot.send_private_msg.assert_awaited_once_with(
                user_id=101,
                message="【每日竞技排名定时任务（第1周）】未查询到心法的角色（共1人，第1-1名）\n1. 梦江南 角色A - id:1001",
            )

        with self.subTest(case="group_fails"):
            module = _load_jobs(admin_qq=[101])
            bot, notify = self._prepare_ranking_job(
                module,
                ranking_result={"code": 0, "defaultWeek": 1, "cache_time": 1},
                ranking_data={
                    "kungfu_statistics": {"dps": {}},
                    "missing_kungfu_lines": ["1. 梦江南 角色A - id:1001"],
                },
                payload={
                    "image_bytes": b"png-bytes",
                    "scope_desc": "前200、前100、前50",
                    "total_valid_data": 199,
                    "processed_label": "前200名",
                },
            )
            bot.get_group_list = AsyncMock(side_effect=RuntimeError("group list unavailable"))

            with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()):
                asyncio.run(module.push_daily_jjc_ranking())

            notify.assert_not_awaited()
            bot.send_group_msg.assert_not_awaited()
            bot.send_private_msg.assert_awaited_once_with(
                user_id=101,
                message="【每日竞技排名定时任务（第1周）】未查询到心法的角色（共1人，第1-1名）\n1. 梦江南 角色A - id:1001",
            )

    def test_notify_jjc_ranking_missing_kungfu_handles_bot_and_admin_qq_edge_cases(self) -> None:
        lines = ["1. 梦江南 角色A - id:1001"]

        with self.subTest(case="bot_none_and_no_driver_bots"):
            module = _load_jobs(admin_qq=[101], bots={})
            asyncio.run(module.notify_jjc_ranking_missing_kungfu(None, lines))

        with self.subTest(case="bot_none_uses_driver_bot"):
            bot = _FakeBot()
            module = _load_jobs(admin_qq=[101], bots={"default": bot})
            with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()):
                asyncio.run(module.notify_jjc_ranking_missing_kungfu(None, lines))
            bot.send_private_msg.assert_awaited_once_with(
                user_id=101,
                message="【每日竞技排名定时任务】未查询到心法的角色（共1人，第1-1名）\n1. 梦江南 角色A - id:1001",
            )

        with self.subTest(case="admin_qq_none_or_empty"):
            for admin_val in (None, []):
                bot = _FakeBot()
                module = _load_jobs(admin_qq=[])
                module.cfg.ADMIN_QQ = admin_val
                asyncio.run(module.notify_jjc_ranking_missing_kungfu(bot, lines))
                bot.send_private_msg.assert_not_awaited()

        with self.subTest(case="admin_qq_single_str_and_dedup_invalid"):
            bot = _FakeBot()
            module = _load_jobs(admin_qq=[])
            module.cfg.ADMIN_QQ = "303"
            with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()):
                asyncio.run(module.notify_jjc_ranking_missing_kungfu(bot, lines))
            bot.send_private_msg.assert_awaited_once_with(
                user_id=303,
                message="【每日竞技排名定时任务】未查询到心法的角色（共1人，第1-1名）\n1. 梦江南 角色A - id:1001",
            )

            bot2 = _FakeBot()
            module.cfg.ADMIN_QQ = [101, "101", "invalid", 202]
            with unittest.mock.patch.object(module.asyncio, "sleep", AsyncMock()):
                asyncio.run(module.notify_jjc_ranking_missing_kungfu(bot2, lines))
            self.assertEqual(
                [call.kwargs["user_id"] for call in bot2.send_private_msg.await_args_list],
                [101, 202],
            )


if __name__ == "__main__":
    unittest.main()
