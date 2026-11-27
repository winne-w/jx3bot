from __future__ import annotations

import asyncio
import threading
import unittest
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import config as cfg
from src.utils import tuilan_auth_alert as alert


class TuilanAuthAlertTests(unittest.TestCase):
    def setUp(self) -> None:
        alert.reset_alert_state()
        alert.clear_runtime_handlers()
        alert.register_alert_handlers(sync_email_sender=lambda msg, subj=None: False)

    def tearDown(self) -> None:
        alert.reset_alert_state()
        alert.clear_runtime_handlers()

    def test_is_tuilan_auth_error_classification_and_strict_mode(self) -> None:
        self.assertTrue(alert.is_tuilan_auth_error({"status_code": 401, "error": "upstream_rejected"}))
        self.assertTrue(alert.is_tuilan_auth_error({"status_code": 403}))
        self.assertTrue(alert.is_tuilan_auth_error({"code": 401, "msg": "Unauthorized"}))
        self.assertTrue(alert.is_tuilan_auth_error({"code": -1, "msg": "请重新登录"}))
        self.assertTrue(alert.is_tuilan_auth_error({"status_code": 400, "text": '{"msg":"票据失效"}'}))
        self.assertTrue(alert.is_tuilan_auth_error({"code": 400, "msg": "推栏票据已过期"}))
        self.assertTrue(alert.is_tuilan_auth_error({"error": "upstream", "message": "ticket invalid"}))

        # 正常响应（包含 jx3api 规范化后的 code=200）和 429 限流不得触发
        self.assertFalse(alert.is_tuilan_auth_error({"code": 0, "msg": "success"}))
        self.assertFalse(alert.is_tuilan_auth_error({"code": 200, "msg": "推栏数据获取成功"}))
        self.assertFalse(alert.is_tuilan_auth_error({"status_code": 429, "msg": "rate limited"}))
        self.assertFalse(alert.is_tuilan_auth_error({"status_code": 500, "error": "request_failed"}))

        # strict_tuilan_only=True（jx3api 同时带 TOKEN 和 TICKET）：不因 JX3API TOKEN 失效误报
        self.assertFalse(
            alert.is_tuilan_auth_error({"status_code": 401, "msg": "invalid token"}, strict_tuilan_only=True)
        )
        self.assertTrue(
            alert.is_tuilan_auth_error({"code": 400, "msg": "推栏票据已失效"}, strict_tuilan_only=True)
        )
        self.assertTrue(
            alert.is_tuilan_auth_error({"code": 401, "msg": "ticket expired"}, strict_tuilan_only=True)
        )

    def test_extract_error_summary_redacts_before_truncating(self) -> None:
        secret = "super-secret-ticket-999888777"
        prefix = "x" * 110
        with patch.object(cfg, "TICKET", secret), patch.object(cfg, "TOKEN", "tok-123456"):
            summary = alert.extract_error_summary({"code": 401, "msg": f"{prefix}{secret} tail"})
            self.assertNotIn("super-secret", summary)
            self.assertIn("***", summary)

    def test_alert_message_uses_equals_command_format(self) -> None:
        msg = alert._build_alert_message(
            source="https://m.pvp.xoyo.com/role/indicator",
            response={"code": 401, "msg": "请重新登录"},
            fingerprint="abcdef123456",
        )
        self.assertIn("/修改配置 TICKET=<新值>", msg)

    def test_sends_qq_and_throttles_until_ticket_changes(self) -> None:
        sent_messages: List[str] = []

        async def fake_qq_sender(message: str) -> bool:
            sent_messages.append(message)
            return True

        now = [1000.0]

        async def scenario() -> None:
            alert.register_alert_handlers(async_qq_sender=fake_qq_sender)
            with patch.object(cfg, "TICKET", "ticket-v1"), \
                    patch.object(cfg, "TUILAN_AUTH_ALERT_COOLDOWN_SECONDS", 3600):
                self.assertTrue(
                    alert.maybe_notify_tuilan_auth_error(
                        source="https://m.pvp.xoyo.com/role/indicator",
                        response={"code": 401, "msg": "请重新登录"},
                        clock=lambda: now[0],
                    )
                )
                await asyncio.sleep(0)
                self.assertEqual(len(sent_messages), 1)

                # 冷却期内重复报错被抑制
                now[0] += 600.0
                self.assertFalse(
                    alert.maybe_notify_tuilan_auth_error(
                        source="https://m.pvp.xoyo.com/role/indicator",
                        response={"code": 401, "msg": "请重新登录"},
                        clock=lambda: now[0],
                    )
                )
                await asyncio.sleep(0)
                self.assertEqual(len(sent_messages), 1)

            # 更换 TICKET 后立刻重新提醒
            with patch.object(cfg, "TICKET", "ticket-v2"), \
                    patch.object(cfg, "TUILAN_AUTH_ALERT_COOLDOWN_SECONDS", 3600):
                self.assertTrue(
                    alert.maybe_notify_tuilan_auth_error(
                        source="TuilanKungfuClient",
                        response={"code": 401, "msg": "登录过期"},
                        clock=lambda: now[0],
                    )
                )
                await asyncio.sleep(0)
                self.assertEqual(len(sent_messages), 2)

        asyncio.run(scenario())

    def test_falls_back_to_email_when_qq_fails_and_retries_after_5min_if_both_fail(self) -> None:
        qq_sender = AsyncMock(return_value=False)
        email_sender = MagicMock(side_effect=[False, True])
        now = [50.0]  # 故意使用小于 cooldown 的小 monotonic 值，验证无负数绕过 Bug

        async def scenario() -> None:
            alert.register_alert_handlers(async_qq_sender=qq_sender, sync_email_sender=email_sender)
            with patch.object(cfg, "TICKET", "ticket-both-fail"), \
                    patch.object(cfg, "TUILAN_AUTH_ALERT_COOLDOWN_SECONDS", 3600):
                # 首次：QQ 和邮件都失败 -> 进入 5 分钟退避
                self.assertTrue(
                    alert.maybe_notify_tuilan_auth_error(
                        source="TuilanKungfuClient",
                        response={"status_code": 401},
                        clock=lambda: now[0],
                    )
                )
                await asyncio.sleep(0.05)
                self.assertEqual(email_sender.call_count, 1)

                # 2 分钟后仍在 5 分钟退避期内 -> 抑制
                now[0] += 120.0
                self.assertFalse(
                    alert.maybe_notify_tuilan_auth_error(
                        source="TuilanKungfuClient",
                        response={"status_code": 401},
                        clock=lambda: now[0],
                    )
                )

                # 再过 4 分钟（累计 6 分钟 > 5 分钟）-> 允许重试，本次邮件成功
                now[0] += 240.0
                self.assertTrue(
                    alert.maybe_notify_tuilan_auth_error(
                        source="TuilanKungfuClient",
                        response={"status_code": 401},
                        clock=lambda: now[0],
                    )
                )
                await asyncio.sleep(0.05)
                self.assertEqual(email_sender.call_count, 2)

        asyncio.run(scenario())

    def test_no_event_loop_falls_back_to_sync_email_and_cross_thread_schedules_on_loop(self) -> None:
        # 1. 无事件循环路径：真正调用同步邮件降级
        email_sender = MagicMock(return_value=True)
        alert.register_alert_handlers(sync_email_sender=email_sender)
        with patch.object(cfg, "TICKET", "ticket-cli"):
            ok = alert.maybe_notify_tuilan_auth_error(
                source="https://m.pvp.xoyo.com/3c/mine/match/detail",
                response={"code": 401, "msg": "请先登录"},
            )
            self.assertTrue(ok)
            email_sender.assert_called_once()

        # 2. 跨线程调用：通过已注册的 main_loop 异步发送 QQ
        alert.reset_alert_state()
        qq_called = threading.Event()

        async def fake_qq_sender(message: str) -> bool:
            qq_called.set()
            return True

        async def run_cross_thread() -> None:
            loop = asyncio.get_running_loop()
            alert.register_alert_handlers(async_qq_sender=fake_qq_sender, loop=loop)
            with patch.object(cfg, "TICKET", "ticket-thread"):
                def worker() -> None:
                    alert.maybe_notify_tuilan_auth_error(
                        source="https://m.pvp.xoyo.com/role/indicator",
                        response={"code": 401, "msg": "请重新登录"},
                    )

                thread = threading.Thread(target=worker)
                thread.start()
                thread.join(timeout=2)
                await asyncio.sleep(0.05)
                self.assertTrue(qq_called.is_set())

        asyncio.run(run_cross_thread())


if __name__ == "__main__":
    unittest.main()
