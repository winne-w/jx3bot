import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta

from src.services.jx3.announcements import format_time, parse_updates, parse_updatesnew
from src.services.jx3.fraud import format_scammer_reply


CST = timezone(timedelta(hours=8))
EPOCH = int(datetime(2026, 11, 23, 8, 30, tzinfo=CST).timestamp())


class TestServerStatusConsumers(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("src.services.jx3.server_status")

    def test_status_items_accepts_list_and_single_object(self):
        row = {"server": "唯我独尊", "status": 1}
        self.assertEqual([row], self.module.server_status_items({"code": 200, "data": [row]}))
        self.assertEqual([row], self.module.server_status_items({"code": 200, "data": row}))

    def test_status_items_rejects_failure_even_with_stale_data(self):
        row = {"server": "唯我独尊", "status": 1}
        for response in (
            {"code": 500, "data": [row]},
            {"code": 200, "error": "request_failed", "data": [row]},
            {"data": [row]},
            {"code": 200, "data": None},
            {"code": 200, "data": "bad shape"},
            None,
        ):
            with self.subTest(response=response):
                self.assertEqual([], self.module.server_status_items(response))

    def test_status_items_filters_non_object_members(self):
        row = {"server": "唯我独尊", "status": 0}
        response = {"code": 200, "data": [None, 1, "bad", row]}
        self.assertEqual([row], self.module.server_status_items(response))
        self.assertEqual([], self.module.server_status_items({"code": 200, "data": []}))

    def test_selector_matches_requested_server_instead_of_first(self):
        wrong = {"server": "梦江南", "status": 0}
        right = {"server": "唯我独尊", "status": 1}
        self.assertEqual(right, self.module.select_server_status({"code": 200, "data": [wrong, right]}, "唯我独尊"))
        self.assertEqual(right, self.module.select_server_status({"code": 200, "data": right}, "唯我独尊"))

    def test_selector_does_not_substitute_another_server(self):
        response = {"code": 200, "data": [{"server": "梦江南", "status": 0}]}
        self.assertIsNone(self.module.select_server_status(response, "唯我独尊"))
        self.assertIsNone(self.module.select_server_status(response, ""))
        self.assertIsNone(self.module.select_server_status({"code": 500, "data": [{"server": "唯我独尊"}]}, "唯我独尊"))


class TestAnnouncementConsumers(unittest.TestCase):
    def test_format_time_supports_legacy_string(self):
        self.assertEqual("11月23日 8点30分", format_time("2026-11-23 08:30:00"))
        self.assertEqual("11月23日 8点", format_time("2026-11-23 08:00:00"))

    def test_format_time_supports_integer_epoch_in_cst(self):
        self.assertEqual("11月23日 8点30分", format_time(EPOCH))
        self.assertEqual("not-a-date", format_time("not-a-date"))

    def test_skill_updates_order_mixed_time_representations(self):
        old = {"id": 1, "title": "武学旧调整", "url": "https://example.test/1", "time": "2026-11-22 08:30:00"}
        new = {"id": 2, "title": "武学新调整", "url": "https://example.test/2", "time": EPOCH}
        unrelated = {"id": 3, "title": "活动", "url": "https://example.test/3", "time": EPOCH + 1}
        actual = parse_updates({"code": 200, "data": [old, unrelated, new]}, keyword="武学")
        self.assertEqual([2], [row["id"] for row in actual])
        self.assertEqual(EPOCH, actual[0]["time"])

    def test_skill_updates_preserves_all_latest_same_time(self):
        rows = [
            {"id": 1, "title": "武学甲", "url": "https://example.test/1", "time": EPOCH},
            {"id": 2, "title": "武学乙", "url": "https://example.test/2", "time": "2026-11-23 08:30:00"},
        ]
        actual = parse_updates({"code": 200, "data": rows}, keyword="武学")
        self.assertEqual({1, 2}, {row["id"] for row in actual})

    def test_skill_updates_failure_returns_no_records(self):
        self.assertEqual([], parse_updates({"code": 500, "msg": "error", "data": []}, keyword="武学"))

    def test_version_records_keep_legacy_date_output(self):
        response = {"code": 200, "data": [
            {"id": 1, "title": "版本旧更新", "url": "https://example.test/1", "date": "2026/11/22"},
            {"id": 2, "title": "版本新更新", "url": "https://example.test/2", "date": "2026/11/23"},
        ]}
        actual = parse_updatesnew(response, keyword="版本")
        self.assertEqual("2", actual[0]["id"])
        self.assertEqual("2026/11/23", actual[0]["time"])


class TestFraudConsumer(unittest.TestCase):
    def test_business_failure_is_not_reported_as_no_fraud_record(self):
        text = format_scammer_reply({"code": 403, "msg": "访问受限", "error": "upstream_error"})
        self.assertIn("失败", text)
        self.assertIn("访问受限", text)
        self.assertNotIn("未查询到", text)

    def test_transport_failure_takes_precedence_over_stale_success_payload(self):
        text = format_scammer_reply({"code": 200, "msg": "请求暂不可用", "error": "request_failed", "data": []})
        self.assertIn("失败", text)
        self.assertIn("请求暂不可用", text)
        self.assertNotIn("未查询到", text)

    def test_failure_without_message_has_safe_fallback(self):
        text = format_scammer_reply({"error": "http_status_500", "text": "private diagnostic body"})
        self.assertIn("失败", text)
        self.assertNotIn("private diagnostic body", text)
        self.assertNotIn("未查询到", text)

    def test_valid_empty_result_retains_no_records_message(self):
        text = format_scammer_reply({"code": 200, "msg": "success", "data": []})
        self.assertIn("未查询到", text)

    def test_legacy_nested_records_still_render(self):
        response = {"code": 200, "data": [{"server": "唯我独尊", "tieba": "剑网3", "data": [
            {"title": "测试记录", "url": "https://example.test/record", "text": "测试内容", "time": EPOCH},
        ]}]}
        text = format_scammer_reply(response)
        self.assertIn("测试记录", text)
        self.assertIn("测试内容", text)
        self.assertIn("https://example.test/record", text)


    def test_current_wrapped_and_single_fraud_records_render_entries(self):
        from src.infra.jx3api_compat import normalize_jx3api_response
        flat = {"server": "唯我独尊", "tieba": "剑网3", "title": "测试记录", "content": "测试内容", "pid": 123, "created": EPOCH}
        for detail in ({"records": [flat]}, flat):
            with self.subTest(detail=detail):
                normalized = normalize_jx3api_response("https://www.jx3api.com/fraud/detail", {"status": 200, "detail": detail})
                text = format_scammer_reply(normalized)
                self.assertIn("测试记录", text)
                self.assertIn("测试内容", text)
                self.assertIn("https://tieba.baidu.com/p/123", text)


class TestFraudUidValidation(unittest.IsolatedAsyncioTestCase):
    async def _invoke(self, uid, explicit=False):
        module = importlib.import_module("src.plugins.jx3bot_handlers.fraud")
        matcher = SimpleNamespace()
        def handle():
            def register(fn):
                matcher.handler = fn
                return fn
            return register
        matcher.handle = handle
        request = AsyncMock(return_value={"code": 200, "msg": "success", "data": []})
        module.register(matcher, get=request, token="unit-test-token")
        bot = SimpleNamespace(send=AsyncMock())
        await matcher.handler(bot, SimpleNamespace(user_id=1), (None, "唯我独尊", uid) if explicit else (uid,))
        return request, bot

    async def test_invalid_uid_is_rejected_without_request_or_exception(self):
        for uid in ("99999", "4000000001", "not-numeric", "²", "9" * 5000):
            with self.subTest(uid=uid[:20]):
                request, bot = await self._invoke(uid)
                request.assert_not_awaited()
                self.assertIn("UID", str(bot.send.call_args.args[1]))

    async def test_documented_uid_boundaries_are_accepted(self):
        for uid in ("100000", "4000000000"):
            with self.subTest(uid=uid):
                request, bot = await self._invoke(uid)
                request.assert_awaited_once()
                self.assertIn("uid=" + uid, request.call_args.args[0])


    async def test_explicit_server_form_uses_uid_and_server(self):
        request, bot = await self._invoke("100000", explicit=True)
        request.assert_awaited_once()
        self.assertIn("uid=100000", request.call_args.args[0])
        from urllib.parse import parse_qs, urlsplit
        self.assertEqual(["唯我独尊"], parse_qs(urlsplit(request.call_args.args[0]).query).get("server"))


if __name__ == "__main__":
    unittest.main()
