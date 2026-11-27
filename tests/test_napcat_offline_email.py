from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import config as real_config
from src.infra import email_notify


class _FakeScheduler:
    def scheduled_job(self, *args: Any, **kwargs: Any) -> Any:
        def decorator(func: Any) -> Any:
            return func

        return decorator


class _FakeLogger:
    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass


def _load_jobs(
    *,
    bots: Optional[Dict[str, Any]] = None,
    email_results: Optional[List[bool]] = None,
) -> Tuple[Any, List[str]]:
    sent_emails: List[str] = []
    results_iter = iter(email_results if email_results is not None else [True] * 10)

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
        "src.plugins.status_monitor.jobs_napcat_test",
    ]
    originals: Dict[str, Any] = {name: sys.modules.get(name) for name in module_names}

    config_mod = types.ModuleType("config")
    config_mod.ADMIN_QQ = [10001]
    config_mod.CURRENT_SEASON = "test-season"
    config_mod.STATUS_MONITOR_OFFLINE_GRACE_SECONDS = 90
    config_mod.STATUS_MONITOR_OFFLINE_FAIL_THRESHOLD = 2
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

    def _fake_send_email(content: str) -> bool:
        sent_emails.append(content)
        return next(results_iter, True)

    notify_mod = types.ModuleType("src.plugins.status_monitor.notify")
    notify_mod.get_NapCat_data = AsyncMock()
    notify_mod.send_email_via_163 = _fake_send_email
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
    spec = importlib.util.spec_from_file_location("src.plugins.status_monitor.jobs_napcat_test", str(module_path))
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
    return module, sent_emails


class NapCatOfflineEmailTests(unittest.TestCase):
    def test_onebot_status_parser_detects_qq_offline_even_when_outer_status_ok(self) -> None:
        module, _ = _load_jobs()
        self.assertTrue(module._is_onebot_status_healthy({"online": True, "good": True})[0])
        self.assertTrue(
            module._is_onebot_status_healthy({"status": "ok", "data": {"online": True, "good": True}})[0]
        )
        self.assertFalse(
            module._is_onebot_status_healthy({"status": "ok", "data": {"online": False, "good": False}})[0]
        )
        self.assertFalse(module._is_onebot_status_healthy({"online": True, "good": False})[0])

    def test_startup_grace_period_suppresses_early_and_alerts_after_expiry(self) -> None:
        module, sent_emails = _load_jobs(bots={})
        module.BOT_INITIALIZED = False

        asyncio.run(module.mail_records())
        asyncio.run(module.mail_records())
        self.assertEqual(sent_emails, [])

        # 宽限期到期后，连续 2 次失败应正常触发告警
        module._napcat_monitor_started_at -= 120.0
        asyncio.run(module.mail_records())
        self.assertEqual(sent_emails, [])
        asyncio.run(module.mail_records())
        self.assertEqual(len(sent_emails), 1)
        self.assertIn("reverse_ws_disconnected", sent_emails[0])

    def test_requires_consecutive_failures_then_alerts_and_recovers(self) -> None:
        bot = types.SimpleNamespace(get_status=AsyncMock(return_value={"online": False, "good": False}))
        driver = types.SimpleNamespace(bots={"3676161887": bot})
        module, sent_emails = _load_jobs()
        module.get_driver = lambda: driver
        module.BOT_INITIALIZED = True

        # 第 1 次失败：不立即发信（防抖）
        asyncio.run(module.mail_records())
        self.assertEqual(sent_emails, [])

        # 第 2 次连续失败：触发掉线邮件
        asyncio.run(module.mail_records())
        self.assertEqual(len(sent_emails), 1)
        self.assertIn("掉线告警", sent_emails[0])
        self.assertIn("qq_offline", sent_emails[0])

        # 第 3 次仍失败：不重复刷屏
        asyncio.run(module.mail_records())
        self.assertEqual(len(sent_emails), 1)

        # 恢复在线：发 1 封恢复邮件
        bot.get_status = AsyncMock(return_value={"online": True, "good": True})
        asyncio.run(module.mail_records())
        self.assertEqual(len(sent_emails), 2)
        self.assertIn("已恢复正常", sent_emails[1])

    def test_multi_bot_does_not_skip_remaining_bots_and_handles_get_status_exception(self) -> None:
        bot_without_api = types.SimpleNamespace()
        bot_throwing = types.SimpleNamespace(get_status=AsyncMock(side_effect=RuntimeError("ws timeout")))
        driver = types.SimpleNamespace(bots={"bot1": bot_without_api, "bot2": bot_throwing})
        module, sent_emails = _load_jobs()
        module.get_driver = lambda: driver
        module.BOT_INITIALIZED = True

        asyncio.run(module.mail_records())
        asyncio.run(module.mail_records())
        self.assertEqual(len(sent_emails), 1)
        self.assertIn("get_status_failed", sent_emails[0])

    def test_failed_email_send_keeps_state_and_retries_next_tick(self) -> None:
        driver = types.SimpleNamespace(bots={})
        module, sent_emails = _load_jobs(email_results=[False, True])
        module.get_driver = lambda: driver
        module.BOT_INITIALIZED = True

        asyncio.run(module.mail_records())
        asyncio.run(module.mail_records())
        self.assertEqual(len(sent_emails), 1)
        self.assertFalse(module._napcat_offline_alert_sent)

        asyncio.run(module.mail_records())
        self.assertEqual(len(sent_emails), 2)
        self.assertTrue(module._napcat_offline_alert_sent)

    def test_email_notify_ignores_placeholder_mail_password(self) -> None:
        with patch.object(real_config, "STATUS_MONITOR_SMTP_USERNAME", "sender@163.com"), \
                patch.object(real_config, "STATUS_MONITOR_SMTP_PASSWORD", ""), \
                patch.object(real_config, "mail", "用于qq掉线提醒 邮箱的tk"), \
                patch.object(real_config, "STATUS_MONITOR_EMAIL_FROM", "sender@163.com"), \
                patch.object(real_config, "STATUS_MONITOR_EMAIL_TO", "admin@qq.com"), \
                patch("smtplib.SMTP_SSL") as smtp_cls:
            self.assertFalse(email_notify.send_email_via_163("test"))
            smtp_cls.assert_not_called()

    def test_email_notify_handles_invalid_port_empty_subject_and_recipient_list(self) -> None:
        smtp_instance = MagicMock()
        smtp_ctx = MagicMock()
        smtp_ctx.__enter__.return_value = smtp_instance
        with patch.object(real_config, "STATUS_MONITOR_SMTP_USERNAME", "sender@163.com"), \
                patch.object(real_config, "STATUS_MONITOR_SMTP_PASSWORD", "auth-code-123"), \
                patch.object(real_config, "STATUS_MONITOR_EMAIL_FROM", "sender@163.com"), \
                patch.object(real_config, "STATUS_MONITOR_EMAIL_TO", ["a@qq.com", " b@qq.com "]), \
                patch.object(real_config, "STATUS_MONITOR_EMAIL_SUBJECT", ""), \
                patch.object(real_config, "STATUS_MONITOR_SMTP_SERVER", "smtp.163.com"), \
                patch.object(real_config, "STATUS_MONITOR_SMTP_PORT", "invalid-port"), \
                patch("smtplib.SMTP_SSL", return_value=smtp_ctx) as smtp_cls:
            ok = email_notify.send_email_via_163("body text")
            self.assertTrue(ok)
            smtp_cls.assert_called_once_with("smtp.163.com", 465, timeout=15)
            sent_msg = smtp_instance.send_message.call_args[0][0]
            self.assertEqual(sent_msg["Subject"], "服务器状态提醒")
            self.assertEqual(sent_msg["To"], "a@qq.com, b@qq.com")


if __name__ == "__main__":
    unittest.main()
