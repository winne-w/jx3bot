import copy
import datetime
import importlib
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from src.infra.jx3api_compat import normalize_jx3api_response


BASE = "https://www.jx3api.com"
LIST_PATHS = (
    "/firework/records", "/event/records", "/exam/search", "/news/records",
    "/news/announce", "/skill/rework", "/role/online/status",
)
OBJECT_PATHS = (
    "/active/calendar", "/arena/recent", "/monster/records", "/role/achievement",
    "/calcd/attribute", "/card/record",
)
FLEX_PATHS = ("/fraud/detail", "/server/status/check")
ALL_PATHS = LIST_PATHS + OBJECT_PATHS + FLEX_PATHS
CST = datetime.timezone(datetime.timedelta(hours=8))


def cst_epoch(value):
    return int(datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST).timestamp())


class TestJx3apiCurrentContract(unittest.TestCase):
    def normalize(self, path, payload):
        return normalize_jx3api_response(BASE + path, {"status": 200, "detail": payload})

    def test_all_fifteen_current_endpoints_adapt_documented_success(self):
        self.assertEqual(15, len(ALL_PATHS))
        for path in ALL_PATHS:
            with self.subTest(path=path):
                payload = [] if path in LIST_PATHS else {}
                actual = self.normalize(path, payload)
                self.assertEqual(200, actual.get("code"))
                self.assertEqual("success", actual.get("msg"))
                self.assertIn("data", actual)
                self.assertFalse(actual.get("error"))

    def test_documented_empty_objects_become_empty_lists_only_for_list_endpoints(self):
        for path in LIST_PATHS:
            with self.subTest(path=path):
                actual = self.normalize(path, {})
                self.assertEqual([], actual.get("data"))
                self.assertEqual("success", actual.get("msg"))
        for path in OBJECT_PATHS + FLEX_PATHS:
            with self.subTest(path=path):
                actual = self.normalize(path, {})
                self.assertIsInstance(actual.get("data"), dict)

    def test_object_and_list_contracts_reject_wrong_payload_types(self):
        for path in OBJECT_PATHS:
            for payload in ([], None, "success", 1, True):
                with self.subTest(path=path, payload=payload):
                    actual = self.normalize(path, payload)
                    self.assertNotEqual("success", actual.get("msg"))
                    self.assertTrue(actual.get("error"))
        for path in LIST_PATHS:
            for payload in ({"not": "a list"}, None, "success", 1, True):
                with self.subTest(path=path, payload=payload):
                    actual = self.normalize(path, payload)
                    self.assertNotEqual("success", actual.get("msg"))
                    self.assertTrue(actual.get("error"))

    def test_current_list_payload_entries_must_be_objects(self):
        for path in LIST_PATHS + FLEX_PATHS:
            for payload in ([None], ["entry"], [False], [1]):
                with self.subTest(path=path, payload=payload):
                    actual = self.normalize(path, payload)
                    self.assertNotEqual("success", actual.get("msg"))
                    self.assertTrue(actual.get("error"))

    def test_flexible_status_and_fraud_interfaces_allow_objects_or_lists(self):
        for path in FLEX_PATHS:
            for payload in ({"server": "测试服", "status": "维护"}, []):
                with self.subTest(path=path, payload=payload):
                    actual = self.normalize(path, payload)
                    self.assertEqual("success", actual.get("msg"))
                    self.assertFalse(actual.get("error"))

    def test_every_current_endpoint_propagates_business_errors(self):
        for path in ALL_PATHS:
            for code in (400, 401, 403, 404, 406, 429, 500):
                with self.subTest(path=path, code=code):
                    original = {"status": code, "detail": "查询条件无效"}
                    actual = normalize_jx3api_response(BASE + path, original)
                    self.assertEqual(code, actual.get("code"))
                    self.assertEqual("查询条件无效", actual.get("msg"))
                    self.assertTrue(actual.get("error"))
                    self.assertEqual({"status": code, "detail": "查询条件无效"}, original)

    def test_error_message_never_matches_legacy_success_sentinel(self):
        for path in ALL_PATHS:
            for message in ("", "success"):
                with self.subTest(path=path, message=message):
                    actual = normalize_jx3api_response(BASE + path, {
                        "status": 403, "detail": message, "code": 200, "msg": "success", "data": {},
                    })
                    self.assertNotEqual("success", actual.get("msg"))
                    self.assertTrue(actual.get("msg"))
                    self.assertTrue(actual.get("error"))

    def test_status_must_be_strict_integer_and_failure_detail_must_be_string(self):
        for status in (True, False, "200", 200.0, None):
            with self.subTest(status=status):
                actual = normalize_jx3api_response(BASE + "/news/records", {
                    "status": status, "detail": [], "msg": "success",
                })
                self.assertNotEqual("success", actual.get("msg"))
                self.assertTrue(actual.get("error"))
        for payload in ({}, [], None, 1):
            with self.subTest(payload=payload):
                actual = normalize_jx3api_response(BASE + "/news/records", {"status": 400, "detail": payload})
                self.assertNotEqual("success", actual.get("msg"))
                self.assertTrue(actual.get("error"))

    def test_legacy_envelopes_and_transport_errors_remain_compatible(self):
        for path in ALL_PATHS:
            for source in (
                {"code": 406, "msg": "接口维护"},
                {"error": "http_status_500", "status_code": 500, "text": "unavailable"},
                {"error": "request_failed", "message": "timeout", "status": 200, "detail": {}},
                {"error": "upstream_failed", "code": 500, "data": [{"receiver": "乙", "mapName": "地图"}]},
            ):
                with self.subTest(path=path, source=source):
                    self.assertEqual(source, normalize_jx3api_response(BASE + path, source))
        source = {"code": 200, "msg": "success", "data": {"history": []}}
        self.assertEqual(source, normalize_jx3api_response(BASE + "/arena/recent", source))

    def test_external_and_lookalike_domains_are_untouched(self):
        for base in ("https://example.test", "https://jx3api.com.example.test", "https://api.jx3api.com"):
            for path in ("/arena/recent", "/firework/records"):
                for source in (
                    {"status": 200, "detail": []},
                    {"code": 200, "data": [{"receiver": "乙", "mapName": "地图"}]},
                ):
                    with self.subTest(base=base, path=path, source=source):
                        self.assertEqual(source, normalize_jx3api_response(base + path, source))

    def test_bare_and_www_hostnames_and_url_query_are_supported(self):
        for base in ("https://jx3api.com", BASE):
            actual = normalize_jx3api_response(base + "/news/records/?limit=3", {"status": 200, "detail": []})
            self.assertEqual("success", actual.get("msg"))
            self.assertEqual([], actual.get("data"))

    def test_field_projections_still_apply_after_new_envelope_conversion(self):
        cases = (
            ("/firework/records", [{"receiver": "乙", "mapName": "扬州", "firework": "真橙之心"}],
             lambda data: self.assertEqual(("乙", "扬州", "真橙之心"), (data[0]["receive"], data[0]["map_name"], data[0]["name"]))),
            ("/monster/records", {"zone": "测试区", "server": "测试服", "globalId": "1", "skillEnergy": 20, "skillStamina": 30},
             lambda data: self.assertEqual(("测试区", "测试服", "1", 20, 30), (data["zoneName"], data["serverName"], data["globalRoleId"], data["gameEnergy"], data["gameStamina"]))),
            ("/exam/search", [{"index": 8, "question": "题目"}], lambda data: self.assertEqual(8, data[0]["id"])),
            ("/fraud/detail", [{"tieba": "剑网3", "pid": 456, "title": "标题", "content": "内容", "created": 123}],
             lambda data: self.assertEqual(("标题", 123), (data[0]["data"][0]["title"], data[0]["data"][0]["time"]))),
            ("/active/calendar", {"lucky": ["宠物"], "weekly": {"conn": ["公共"], "raid": ["团队"]}},
             lambda data: self.assertEqual((["宠物"], ["公共", "团队"]), (data["luck"], data["team"]))),
        )
        for path, payload, check in cases:
            with self.subTest(path=path):
                source = {"status": 200, "detail": payload}
                before = copy.deepcopy(source)
                actual = normalize_jx3api_response(BASE + path, source)
                self.assertEqual(before, source)
                check(actual["data"])

    def test_news_category_and_timestamp_use_documented_fallbacks(self):
        payload = [
            {"catid": 99, "desc": {"inputtime": 123, "asktime": "2026-11-23 20:00:00"}, "date": "2026-11-22"},
            {"catid": 98, "desc": {"asktime": "2026-11-23 20:00:00"}, "date": "2026-11-22"},
            {"catid": 97, "date": "2026-11-22"},
        ]
        data = self.normalize("/news/records", payload)["data"]
        self.assertEqual([99, 98, 97], [item["id"] for item in data])
        self.assertEqual([123, cst_epoch("2026-11-23 20:00:00"), cst_epoch("2026-11-22 00:00:00")],
                         [item["time"] for item in data])

    def test_announcement_consumers_keep_normalized_publication_time(self):
        from src.services.jx3.announcements import parse_updateshuodong, parse_updatesnew
        response = self.normalize("/news/records", [{
            "catid": 99, "title": "活动版本公告", "url": "https://example.test/article",
            "desc": {"inputtime": 1795435200}, "date": "2026-11-23",
        }])
        for parser, keyword in ((parse_updateshuodong, "活动"), (parse_updatesnew, "版本")):
            with self.subTest(parser=parser.__name__):
                result = parser(response, keyword=keyword)
                self.assertEqual(1, len(result))
                self.assertEqual(1795435200, result[0]["time"])

    def test_existing_news_id_and_time_are_not_overwritten(self):
        actual = self.normalize("/news/records", [{"id": 7, "catid": 99, "time": 456, "date": "2026-11-22"}])
        self.assertEqual((7, 456), (actual["data"][0]["id"], actual["data"][0]["time"]))

    def test_skill_datetime_is_converted_with_explicit_china_timezone(self):
        data = self.normalize("/skill/rework", [{"time": "2026-11-12 08:50:00"}])["data"]
        self.assertEqual(cst_epoch("2026-11-12 08:50:00"), data[0]["time"])
        self.assertIsInstance(data[0]["time"], int)

    def test_null_event_timestamp_is_safe_for_existing_time_filters(self):
        source = {"status": 200, "detail": [{"name": "奇遇", "time": None}]}
        actual = normalize_jx3api_response(BASE + "/event/records", source)
        self.assertEqual(0, actual["data"][0]["time"])
        self.assertIsNone(source["detail"][0]["time"])

    def test_server_status_projects_legacy_values_for_single_or_list_payloads(self):
        row = {"server": "测试服", "zone": "测试区", "status": "维护"}
        for payload in (row, [row]):
            with self.subTest(payload=payload):
                actual = self.normalize("/server/status/check", payload)
                result = actual["data"]
                item = result[0] if isinstance(result, list) else result
                self.assertEqual(0, item["legacyStatus"])
                self.assertIsInstance(item["time"], int)
                self.assertEqual("维护", item["status"])


class TestJx3apiAnnouncementFailures(unittest.IsolatedAsyncioTestCase):
    async def test_announcement_handlers_report_business_failure_not_missing_records(self):
        from src.plugins.jx3bot_handlers.announcements import register

        class Matcher:
            def __init__(self):
                self.handlers = []

            def handle(self):
                def save(fn):
                    self.handlers.append(fn)
                    return fn
                return save

        matchers = [Matcher() for _ in range(3)]
        fetch = AsyncMock(return_value={"code": 403, "msg": "访问受限", "error": "upstream_error"})
        register(*matchers, jiaoyiget=fetch, skill_records_url=BASE + "/skill/rework")
        for index, matcher in enumerate(matchers):
            with self.subTest(handler=index):
                bot = SimpleNamespace(send=AsyncMock())
                event = SimpleNamespace()
                await matcher.handlers[0](bot, event, (None,))
                bot.send.assert_awaited_once()
                text = str(bot.send.call_args.args[1])
                self.assertIn("访问受限", text)
                self.assertNotIn("未找到", text)
                self.assertNotIn("未找活动", text)


class TestJx3apiCurrentRequests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = importlib.import_module("src.infra.jx3api_get")
        self.cache = Mock()
        self.cache.get.return_value = None
        self.cache_patch = patch.object(self.module, "_cache", self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    async def request(self, url, response, **kwargs):
        call = AsyncMock(return_value=response)
        with patch.object(self.module.HttpClient, "arequest_json", call):
            result = await self.module.get(url, server="测试服", name="测试角色", token="unit-test-token", **kwargs)
        return result, call.call_args

    async def test_all_jx3api_tokens_are_header_credentials(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                _, call = await self.request(BASE + path, {"code": 200, "msg": "success", "data": {}})
                self.assertNotIn("token", call.kwargs["params"])
                self.assertEqual("unit-test-token", call.kwargs.get("headers", {}).get("token"))

    async def test_ticket_only_reaches_documented_arena_get_endpoint(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                _, call = await self.request(BASE + path, {"code": 200, "msg": "success", "data": {}}, ticket="unit-test-ticket")
                self.assertEqual(path == "/arena/recent", "ticket" in call.kwargs["params"])
                if path == "/arena/recent":
                    self.assertEqual("unit-test-ticket", call.kwargs["params"]["ticket"])

    async def test_non_jx3api_request_preserves_query_credentials(self):
        _, call = await self.request("https://example.test/arena/recent", {"status": 200, "detail": {}}, ticket="unit-test-ticket")
        self.assertEqual("unit-test-token", call.kwargs["params"].get("token"))
        self.assertEqual("unit-test-ticket", call.kwargs["params"].get("ticket"))
        self.assertFalse(call.kwargs.get("headers", {}).get("token"))

    async def test_every_current_business_failure_is_not_cached(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                self.cache.set.reset_mock()
                result, _ = await self.request(BASE + path, {"status": 404, "detail": "角色未收录"})
                self.assertTrue(result.get("error"))
                self.assertEqual("角色未收录", result.get("msg"))
                self.cache.set.assert_not_called()

    async def test_existing_url_query_is_preserved_when_header_auth_is_added(self):
        from src.infra import jx3api_get
        request = AsyncMock(return_value={"status": 200, "detail": []})
        cache = Mock()
        cache.get.return_value = None
        with patch.object(jx3api_get.HttpClient, "arequest_json", request), patch.object(jx3api_get, "_cache", cache):
            await jx3api_get.get(BASE + "/fraud/detail?uid=100000&server=测试服", token="unit-token")
        self.assertEqual("100000", request.call_args.kwargs["params"]["uid"])
        self.assertEqual("测试服", request.call_args.kwargs["params"]["server"])
        self.assertEqual("unit-token", request.call_args.kwargs["headers"]["token"])
        self.assertNotIn("token", request.call_args.kwargs["params"])

    async def test_achievement_configuration_uses_current_documented_path(self):
        cfg = importlib.import_module("config")
        self.assertEqual(BASE + "/role/achievement", cfg.API_URLS["资历查询"])
        _, call = await self.request(cfg.API_URLS["资历查询"], {"status": 200, "detail": {}}, zili=3)
        self.assertEqual(3, call.kwargs["params"]["class"])
        self.assertNotIn("ticket", call.kwargs["params"])


if __name__ == "__main__":
    unittest.main()
