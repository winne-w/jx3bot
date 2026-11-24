import copy
import importlib
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.infra.jx3api_compat import normalize_jx3api_response


ARENA_URL = "https://www.jx3api.com/arena/recent"


class TestArenaRecentResponse(unittest.TestCase):
    def test_current_success_exposes_payload_to_existing_consumer(self):
        payload = {"roleName": "测试角色", "performance": {"3v3": {"mmr": 2385}},
                   "history": [{"pvpType": 3, "won": True, "totalMmr": 2385}]}
        source = {"status": 200, "detail": payload}
        before = copy.deepcopy(source)
        actual = normalize_jx3api_response(ARENA_URL, source)
        self.assertEqual("success", actual.get("msg"))
        self.assertEqual(200, actual.get("code"))
        self.assertEqual(payload, actual.get("data"))
        self.assertFalse(actual.get("error"))
        self.assertEqual(before, source)
        actual["data"]["history"][0]["won"] = False
        self.assertEqual(before, source)

    def test_documented_empty_object_is_success(self):
        actual = normalize_jx3api_response(ARENA_URL, {"status": 200, "detail": {}})
        self.assertEqual("success", actual.get("msg"))
        self.assertEqual({}, actual.get("data"))

    def test_current_business_errors_preserve_code_and_message(self):
        for code in (400, 401, 403, 406, 429, 500):
            with self.subTest(code=code):
                source = {"status": code, "detail": "查询被拒绝"}
                actual = normalize_jx3api_response(ARENA_URL, source)
                self.assertEqual(code, actual.get("code"))
                self.assertEqual("查询被拒绝", actual.get("msg"))
                self.assertTrue(actual.get("error"))
                self.assertEqual({"status": code, "detail": "查询被拒绝"}, source)

    def test_business_failure_message_cannot_equal_legacy_success_sentinel(self):
        actual = normalize_jx3api_response(ARENA_URL, {"status": 403, "detail": "success"})
        self.assertNotEqual("success", actual.get("msg"))
        self.assertTrue(actual.get("error"))

    def test_empty_business_error_has_non_success_fallback_message(self):
        actual = normalize_jx3api_response(ARENA_URL, {"status": 500, "detail": ""})
        self.assertTrue(actual.get("msg"))
        self.assertNotEqual("success", actual.get("msg"))
        self.assertTrue(actual.get("error"))

    def test_current_failure_cannot_reuse_stray_legacy_success_fields(self):
        actual = normalize_jx3api_response(ARENA_URL, {
            "status": 403, "detail": "访问受限", "msg": "success", "code": 200,
            "data": {"history": [{"won": True}]},
        })
        self.assertEqual(403, actual.get("code"))
        self.assertEqual("访问受限", actual.get("msg"))
        self.assertTrue(actual.get("error"))

    def test_malformed_current_success_is_not_accepted(self):
        for detail in (None, [], "success", 1, True):
            with self.subTest(detail=detail):
                actual = normalize_jx3api_response(ARENA_URL, {"status": 200, "detail": detail})
                self.assertNotEqual("success", actual.get("msg"))
                self.assertTrue(actual.get("error"))
        actual = normalize_jx3api_response(ARENA_URL, {"status": 200})
        self.assertNotEqual("success", actual.get("msg"))
        self.assertTrue(actual.get("error"))

    def test_status_must_be_an_integer(self):
        for status in ("200", 200.0, True, False, None):
            with self.subTest(status=status):
                actual = normalize_jx3api_response(ARENA_URL, {
                    "status": status, "detail": {}, "msg": "success", "code": 200,
                })
                self.assertNotEqual("success", actual.get("msg"))
                self.assertTrue(actual.get("error"))

    def test_business_error_detail_must_be_a_string(self):
        for detail in ({}, [], None, 42):
            with self.subTest(detail=detail):
                actual = normalize_jx3api_response(ARENA_URL, {"status": 403, "detail": detail})
                self.assertNotEqual("success", actual.get("msg"))
                self.assertTrue(actual.get("error"))

    def test_legacy_success_and_failure_are_unchanged(self):
        for source in (
            {"code": 200, "msg": "success", "data": {"history": []}},
            {"code": 406, "msg": "接口暂不可用"},
        ):
            with self.subTest(source=source):
                self.assertEqual(source, normalize_jx3api_response(ARENA_URL, source))

    def test_transport_error_is_never_converted_to_success(self):
        source = {"error": "http_status_500", "status_code": 500, "text": "failed",
                  "status": 200, "detail": {}}
        self.assertEqual(source, normalize_jx3api_response(ARENA_URL, source))

    def test_new_envelope_does_not_change_other_endpoints(self):
        source = {"status": 200, "detail": {"roleName": "测试角色"}}
        actual = normalize_jx3api_response("https://www.jx3api.com/other/recent", source)
        self.assertEqual(source, actual)

    def test_trailing_slash_and_query_still_identify_arena_endpoint(self):
        actual = normalize_jx3api_response(ARENA_URL + "/?mode=33", {"status": 200, "detail": {}})
        self.assertEqual("success", actual.get("msg"))
        self.assertEqual({}, actual.get("data"))


class TestArenaRecentConsumer(unittest.TestCase):
    def _build(self, payload):
        from src.services.jx3.query_context import build_jjc_spec_or_text
        normalized = normalize_jx3api_response(ARENA_URL, {"status": 200, "detail": payload})
        return build_jjc_spec_or_text(
            data=normalized, role_name="测试角色", server="测试服",
            time_filter=str, jjc_time_filter=str, duration_filter=str, random_text="测试",
        )

    def test_documented_empty_payload_produces_existing_no_record_guidance(self):
        spec, error_text = self._build({})
        self.assertIsNone(spec)
        self.assertIsInstance(error_text, str)
        self.assertIn("未找到", error_text)
        self.assertIn("测试角色", error_text)

    def test_valid_current_payload_builds_existing_template_spec(self):
        payload = {"roleName": "测试角色", "serverName": "测试服",
                   "performance": {"2v2": [], "3v3": {"mmr": 2385}, "5v5": []},
                   "history": [{"pvpType": 3, "won": True, "totalMmr": 2385}]}
        spec, error_text = self._build(payload)
        self.assertIsNone(error_text)
        self.assertIsNotNone(spec)
        self.assertEqual("竞技查询.html", spec.template_name)
        self.assertEqual(payload, spec.context["items"])


class TestArenaRecentRequest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = importlib.import_module("src.infra.jx3api_get")
        self.cache = Mock()
        self.cache.get.return_value = None
        self.cache_patch = patch.object(self.module, "_cache", self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    async def test_arena_token_is_sent_as_header_with_query_identity_and_ticket(self):
        request = AsyncMock(return_value={"status": 200, "detail": {"history": []}})
        with patch.object(self.module.HttpClient, "arequest_json", request):
            actual = await self.module.get(ARENA_URL, server="测试服", name="测试角色",
                                           token="unit-test-token", ticket="unit-test-ticket")
        args, kwargs = request.call_args
        self.assertEqual(("GET", ARENA_URL), args)
        self.assertEqual({"server": "测试服", "name": "测试角色", "ticket": "unit-test-ticket"}, kwargs["params"])
        self.assertEqual("unit-test-token", kwargs.get("headers", {}).get("token"))
        self.assertEqual("success", actual.get("msg"))
        self.assertEqual({"history": []}, actual.get("data"))
        self.cache.set.assert_called_once()

    async def test_non_arena_request_keeps_token_in_query(self):
        request = AsyncMock(return_value={"code": 200, "msg": "success", "data": []})
        url = "https://example.invalid/firework/records"
        with patch.object(self.module.HttpClient, "arequest_json", request):
            await self.module.get(url, server="测试服", name="测试角色", token="unit-test-token")
        kwargs = request.call_args.kwargs
        self.assertEqual("unit-test-token", kwargs["params"]["token"])
        self.assertFalse(kwargs.get("headers", {}).get("token"))

    async def test_current_business_failure_is_not_cached(self):
        request = AsyncMock(return_value={"status": 429, "detail": "请稍后重试"})
        with patch.object(self.module.HttpClient, "arequest_json", request):
            actual = await self.module.get(ARENA_URL, server="测试服", name="测试角色", token="unit-test-token")
        self.assertEqual("请稍后重试", actual.get("msg"))
        self.assertTrue(actual.get("error"))
        self.cache.set.assert_not_called()

    async def test_no_token_omits_token_header(self):
        request = AsyncMock(return_value={"status": 401, "detail": "令牌缺失"})
        with patch.object(self.module.HttpClient, "arequest_json", request):
            await self.module.get(ARENA_URL, server="测试服", name="测试角色")
        kwargs = request.call_args.kwargs
        self.assertNotIn("token", kwargs["params"])
        self.assertFalse(kwargs.get("headers", {}).get("token"))


if __name__ == "__main__":
    unittest.main()
