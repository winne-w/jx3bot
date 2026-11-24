import asyncio
import copy
import importlib
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit


ROWS = [
    {"cacheTime": 1795360375, "equipType": "秘境挑战", "kungfuName": "冰心诀", "seasonName": "苍生铸世"},
    {"cacheTime": 1795270451, "equipType": "竞技对抗", "kungfuName": "云裳心经", "seasonName": "苍生铸世"},
    {"cacheTime": 1777557811, "equipType": "秘境挑战", "kungfuName": "云裳心经", "seasonName": "暗影千机"},
]


def detail(kungfu="云裳心经", equip_type="竞技对抗", **overrides):
    payload = {"kungfuName": kungfu, "equipType": equip_type, "roleName": "桃桃白糖", "serverName": "唯我独尊",
               "cacheTime": 1795270451, "seasonName": "苍生铸世", "equipList": [{"itemName": "测试装备"}]}
    payload.update(overrides)
    return {"code": 200, "msg": "success", "data": payload}


class TestEquipmentCommand(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("src.services.jx3.equipment_query")

    def parse(self, raw):
        return self.module.parse_equipment_command(raw, server_names=("唯我独尊", "长安城"))

    def test_unfiltered_legacy_identity_forms_are_preserved(self):
        command = self.parse("桃桃白糖")
        self.assertEqual((None, "桃桃白糖", None, None), (command.server, command.name, command.kungfu, command.equip_type))
        self.assertEqual(("桃桃白糖", None, None), command.identity_groups())
        command = self.parse("唯我独尊 桃桃白糖")
        self.assertEqual(("唯我独尊", "桃桃白糖"), (command.server, command.name))
        self.assertEqual((None, "唯我独尊", "桃桃白糖"), command.identity_groups())

    def test_full_kungfu_and_type_aliases_can_be_supplied_in_either_order(self):
        for raw in ("桃桃白糖 云裳心经 pvp", "桃桃白糖 PVP 云裳心经", "桃桃白糖 云裳心经 竞技对抗"):
            with self.subTest(raw=raw):
                command = self.parse(raw)
                self.assertEqual((None, "桃桃白糖", "云裳心经", "竞技对抗"),
                                 (command.server, command.name, command.kungfu, command.equip_type))
        for alias, expected in (("PVE", "秘境挑战"), ("pVe", "秘境挑战"), ("秘境挑战", "秘境挑战"), ("休闲", "休闲"), ("通用", "通用")):
            with self.subTest(alias=alias):
                self.assertEqual(expected, self.parse("桃桃白糖 " + alias).equip_type)

    def test_named_options_accept_documented_chinese_and_english_keys(self):
        for raw in ("唯我独尊 桃桃白糖 心法=云裳心经 类型=PVP", "桃桃白糖 type=pvp kungfu=云裳心经"):
            with self.subTest(raw=raw):
                command = self.parse(raw)
                self.assertEqual("桃桃白糖", command.name)
                self.assertEqual("云裳心经", command.kungfu)
                self.assertEqual("竞技对抗", command.equip_type)

    def test_single_filter_is_not_mistaken_for_server_or_character(self):
        command = self.parse("桃桃白糖 云裳心经")
        self.assertEqual((None, "桃桃白糖", "云裳心经", None), (command.server, command.name, command.kungfu, command.equip_type))
        command = self.parse("唯我独尊 桃桃白糖 PVP")
        self.assertEqual(("唯我独尊", "桃桃白糖", None, "竞技对抗"), (command.server, command.name, command.kungfu, command.equip_type))

    def test_single_tokens_and_known_server_role_tokens_are_kept_as_identity(self):
        for role in ("pvp", "PVE", "冰心诀", "通用"):
            with self.subTest(role=role):
                command = self.parse(role)
                self.assertEqual(role, command.name)
                self.assertIsNone(command.equip_type)
                self.assertIsNone(command.kungfu)
                command = self.parse("唯我独尊 " + role + " 云裳心经")
                self.assertEqual(("唯我独尊", role, "云裳心经"), (command.server, command.name, command.kungfu))

    def test_unknown_kungfu_with_valid_filter_is_not_reinterpreted_as_server_and_name(self):
        for raw in ("桃桃白糖 云裳 PVP", "桃桃白糖 不存在心法 类型=PVP"):
            with self.subTest(raw=raw):
                with self.assertRaises(self.module.EquipmentQueryError):
                    self.parse(raw)

    def test_unknown_two_token_server_form_remains_resolver_responsibility(self):
        command = self.parse("未知区服 桃桃白糖")
        self.assertEqual(("未知区服", "桃桃白糖"), (command.server, command.name))

    def test_duplicate_conflicting_unknown_or_incomplete_options_raise_useful_errors(self):
        for raw in ("", " ", "桃桃白糖 PVP PVP", "桃桃白糖 PVE PVP", "桃桃白糖 云裳心经 云裳心经",
                    "桃桃白糖 云裳心经 心法=云裳心经", "桃桃白糖 类型=", "桃桃白糖 心法=", "桃桃白糖 foo=bar",
                    "桃桃白糖 类型=不存在", "桃桃白糖 心法=云裳", "桃桃白糖 不存在 未知"):
            with self.subTest(raw=raw):
                with self.assertRaises(self.module.EquipmentQueryError) as caught:
                    self.parse(raw)
                self.assertTrue(str(caught.exception))


class TestEquipmentCombinationSelection(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("src.services.jx3.equipment_query")

    def test_kungfu_only_uses_latest_valid_matching_combination(self):
        before = copy.deepcopy(ROWS)
        actual = self.module.select_equipment_combination(ROWS, kungfu="云裳心经")
        self.assertEqual(("云裳心经", "竞技对抗"), actual)
        self.assertEqual(before, ROWS)

    def test_type_only_uses_latest_matching_kungfu(self):
        actual = self.module.select_equipment_combination(ROWS, equip_type="秘境挑战")
        self.assertEqual(("冰心诀", "秘境挑战"), actual)

    def test_exact_combination_and_cross_season_duplicates_do_not_create_ambiguity(self):
        rows = [dict(ROWS[1]), dict(ROWS[1], seasonName="旧赛季", cacheTime=100)]
        self.assertEqual(("云裳心经", "竞技对抗"), self.module.select_equipment_combination(rows, kungfu="云裳心经"))
        self.assertEqual(("云裳心经", "竞技对抗"), self.module.select_equipment_combination(rows, kungfu="云裳心经", equip_type="竞技对抗"))

    def test_no_matching_valid_combination_is_an_explicit_error(self):
        for rows in ([], [{"kungfuName": "不存在", "equipType": "竞技对抗", "cacheTime": 100}], [{}]):
            with self.subTest(rows=rows):
                with self.assertRaises(self.module.EquipmentQueryError):
                    self.module.select_equipment_combination(rows, kungfu="冰心诀")
        with self.assertRaises(self.module.EquipmentQueryError):
            self.module.select_equipment_combination(ROWS, kungfu="冰心诀", equip_type="休闲")

    def test_multi_combination_requires_valid_finite_positive_times_for_every_candidate(self):
        for invalid in (None, 0, -1, True, "not-a-time", float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                rows = [dict(ROWS[1]), dict(ROWS[2], cacheTime=invalid)]
                with self.assertRaises(self.module.EquipmentQueryError):
                    self.module.select_equipment_combination(rows, kungfu="云裳心经")

    def test_equal_latest_time_between_different_pairs_requires_disambiguation(self):
        rows = [dict(ROWS[1]), dict(ROWS[2], cacheTime=ROWS[1]["cacheTime"])]
        with self.assertRaises(self.module.EquipmentQueryError) as caught:
            self.module.select_equipment_combination(rows, kungfu="云裳心经")
        message = str(caught.exception)
        self.assertIn("秘境挑战", message)
        self.assertIn("竞技对抗", message)


class TestEquipmentQueryFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = importlib.import_module("src.services.jx3.equipment_query")

    async def query(self, fetch, **kwargs):
        return await self.module.fetch_equipment_query(server="唯我独尊", name="桃桃白糖", fetch=fetch, **kwargs)

    def assert_detail_call(self, call, kungfu="云裳心经", equip_type="竞技对抗"):
        self.assertEqual("/calcd/detail", urlsplit(call.kwargs["url"]).path)
        self.assertEqual({"kungfu": [kungfu], "type": [equip_type], "format": ["calcd"]}, parse_qs(urlsplit(call.kwargs["url"]).query))
        self.assertEqual("唯我独尊", call.kwargs["server"])
        self.assertEqual("桃桃白糖", call.kwargs["name"])
        self.assertIn("token", call.kwargs)
        self.assertNotIn("ticket", call.kwargs)

    async def test_default_query_preserves_attribute_endpoint_without_records(self):
        payload = detail()
        fetch = AsyncMock(return_value=payload)
        actual = await self.query(fetch)
        self.assertEqual(payload, actual)
        fetch.assert_awaited_once()
        self.assertEqual("/calcd/attribute", urlsplit(fetch.call_args.kwargs["url"]).path)
        self.assertNotIn("kungfu", parse_qs(urlsplit(fetch.call_args.kwargs["url"]).query))

    async def test_two_explicit_filters_query_detail_directly_with_encoded_parameters(self):
        fetch = AsyncMock(return_value=detail())
        actual = await self.query(fetch, kungfu="云裳心经", equip_type="竞技对抗")
        fetch.assert_awaited_once()
        self.assert_detail_call(fetch.call_args)
        self.assertEqual("苍生铸世", actual["data"]["seasonName"])
        self.assertEqual(1795270451, actual["data"]["cacheTime"])

    async def test_partial_filter_resolves_records_then_fetches_exact_detail(self):
        fetch = AsyncMock(side_effect=[{"msg": "success", "data": {"roleName": "桃桃白糖", "equipList": copy.deepcopy(ROWS)}}, detail()])
        actual = await self.query(fetch, kungfu="云裳心经")
        self.assertEqual(2, fetch.await_count)
        self.assertEqual("/calcd/records", urlsplit(fetch.await_args_list[0].kwargs["url"]).path)
        self.assert_detail_call(fetch.await_args_list[1])
        self.assertEqual("云裳心经", actual["data"]["kungfuName"])

    async def test_type_only_resolves_latest_then_checks_returned_combination(self):
        fetch = AsyncMock(side_effect=[{"msg": "success", "data": {"equipList": copy.deepcopy(ROWS)}}, detail("冰心诀", "秘境挑战")])
        await self.query(fetch, equip_type="秘境挑战")
        self.assert_detail_call(fetch.await_args_list[1], "冰心诀", "秘境挑战")

    async def test_malformed_records_equipment_list_is_not_reported_as_uncollected(self):
        for rows in (None, {}, "not-a-list", 123):
            with self.subTest(rows=rows):
                fetch = AsyncMock(return_value={"msg": "success", "data": {"equipList": rows}})
                with self.assertRaisesRegex(self.module.EquipmentQueryError, "格式"):
                    await self.query(fetch, kungfu="云裳心经")
                fetch.assert_awaited_once()

    async def test_records_identity_mismatch_is_rejected_before_detail_query(self):
        for overrides in ({"roleName": "别的角色"}, {"serverName": "别的服"}):
            with self.subTest(overrides=overrides):
                payload = {"equipList": copy.deepcopy(ROWS), "roleName": "桃桃白糖", "serverName": "唯我独尊"}
                payload.update(overrides)
                fetch = AsyncMock(return_value={"msg": "success", "data": payload})
                with self.assertRaises(self.module.EquipmentQueryError):
                    await self.query(fetch, kungfu="云裳心经")
                fetch.assert_awaited_once()

    async def test_two_stage_queries_share_one_absolute_budget(self):
        async def delayed_fetch(**kwargs):
            await asyncio.sleep(0.03)
            if urlsplit(kwargs["url"]).path == "/calcd/records":
                return {"msg": "success", "data": {"equipList": copy.deepcopy(ROWS)}}
            return detail()
        fetch = AsyncMock(side_effect=delayed_fetch)
        with patch.object(self.module, "QUERY_TIMEOUT_SECONDS", 0.05):
            with self.assertRaises(self.module.EquipmentQueryError):
                await asyncio.wait_for(self.query(fetch, kungfu="云裳心经"), timeout=0.4)
        self.assertEqual(2, fetch.await_count)

    async def test_missing_records_or_unavailable_selection_never_falls_back_to_current_attribute(self):
        for payload in ({}, {"equipList": []}, {"equipList": [{"kungfuName": "云裳心经", "equipType": "休闲"}]}):
            with self.subTest(payload=payload):
                fetch = AsyncMock(return_value={"msg": "success", "data": payload})
                with self.assertRaises(self.module.EquipmentQueryError):
                    await self.query(fetch, kungfu="冰心诀")
                fetch.assert_awaited_once()
                self.assertEqual("/calcd/records", urlsplit(fetch.call_args.kwargs["url"]).path)

    async def test_missing_or_conflicting_detail_fields_are_not_presented_as_requested_loadout(self):
        for payload in ({}, {"kungfuName": "冰心诀", "equipType": "竞技对抗"}, {"kungfuName": "云裳心经"},
                        {"kungfuName": "云裳心经", "equipType": "秘境挑战"}):
            with self.subTest(payload=payload):
                fetch = AsyncMock(return_value={"msg": "success", "data": payload})
                with self.assertRaises(self.module.EquipmentQueryError):
                    await self.query(fetch, kungfu="云裳心经", equip_type="竞技对抗")
                fetch.assert_awaited_once()

    async def test_explicit_details_reject_other_returned_character_or_server(self):
        for overrides in ({"roleName": "别的角色"}, {"serverName": "别的服"}):
            with self.subTest(overrides=overrides):
                fetch = AsyncMock(return_value=detail(**overrides))
                with self.assertRaises(self.module.EquipmentQueryError):
                    await self.query(fetch, kungfu="云裳心经", equip_type="竞技对抗")

    async def test_business_or_transport_errors_propagate_without_attribute_fallback(self):
        from src.services.jx3.command_context import CommandContextError
        fetch = AsyncMock(side_effect=CommandContextError("上游权限不足", at_user=True))
        with self.assertRaisesRegex(CommandContextError, "上游权限不足"):
            await self.query(fetch, kungfu="云裳心经", equip_type="竞技对抗")
        fetch.assert_awaited_once()

    async def test_one_absolute_budget_bounds_record_and_detail_work(self):
        async def slow_fetch(**kwargs):
            await asyncio.sleep(1)
            return detail()
        fetch = AsyncMock(side_effect=slow_fetch)
        with patch.object(self.module, "QUERY_TIMEOUT_SECONDS", 0.03):
            with self.assertRaises((self.module.EquipmentQueryError, asyncio.TimeoutError)):
                await asyncio.wait_for(self.query(fetch, kungfu="云裳心经"), timeout=0.3)
        fetch.assert_awaited_once()


class TestEquipmentRawCommandHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from jinja2 import Environment
        self.module = importlib.import_module("src.plugins.jx3bot_handlers.queries")
        self.config = importlib.import_module("config")
        class Matcher:
            def handle(self):
                def save(fn):
                    self.handler = fn
                    return fn
                return save
        self.matchers = {name: Matcher() for name in ("yanhua", "qiyu", "zhuangfen", "jjc", "fuben", "online")}
        self.module.register(env=Environment(), **{name + "_matcher": matcher for name, matcher in self.matchers.items()})
        self.bot = SimpleNamespace(send=AsyncMock())
        self.event = SimpleNamespace(group_id=123, user_id=456)

    def groups(self, message):
        match = re.fullmatch(self.config.REGEX_PATTERNS["装备查询"], message)
        self.assertIsNotNone(match)
        self.assertEqual(1, len(match.groups()))
        return match.groups()

    async def test_actual_raw_regex_options_are_forwarded_to_query_service(self):
        resolver = AsyncMock(return_value=("唯我独尊", "桃桃白糖"))
        fetch = AsyncMock(return_value=detail())
        renderer = AsyncMock()
        with patch.object(self.module, "equipment_server_names", return_value=("唯我独尊",)), \
             patch.object(self.module, "resolve_server_and_name", resolver), \
             patch.object(self.module, "fetch_equipment_query", fetch), \
             patch.object(self.module, "render_and_send_template_image", renderer):
            await self.matchers["zhuangfen"].handler(self.bot, self.event,
                self.groups("装备 唯我独尊 桃桃白糖 类型=PVP 心法=云裳心经"))
        resolver.assert_awaited_once_with((None, "唯我独尊", "桃桃白糖"), group_id=123)
        fetch.assert_awaited_once()
        self.assertEqual(("唯我独尊", "桃桃白糖", "云裳心经", "竞技对抗"),
            tuple(fetch.call_args.kwargs[key] for key in ("server", "name", "kungfu", "equip_type")))
        renderer.assert_awaited_once()
        self.bot.send.assert_not_awaited()

    async def test_raw_parse_error_does_not_query_or_render(self):
        resolver = AsyncMock()
        fetch = AsyncMock()
        renderer = AsyncMock()
        send = AsyncMock()
        with patch.object(self.module, "equipment_server_names", return_value=("唯我独尊",)), \
             patch.object(self.module, "resolve_server_and_name", resolver), \
             patch.object(self.module, "fetch_equipment_query", fetch), \
             patch.object(self.module, "render_and_send_template_image", renderer), \
             patch.object(self.module, "send_text", send):
            await self.matchers["zhuangfen"].handler(self.bot, self.event, self.groups("装备 桃桃白糖 foo=bar"))
        resolver.assert_not_awaited()
        fetch.assert_not_awaited()
        renderer.assert_not_awaited()
        send.assert_awaited_once()
        self.assertIn("用法", send.call_args.args[2])


class TestEquipmentDetailContractAndCache(unittest.IsolatedAsyncioTestCase):
    async def test_detail_and_records_success_envelopes_are_supported(self):
        from src.infra.jx3api_compat import normalize_jx3api_response
        for path in ("/calcd/detail", "/calcd/records"):
            with self.subTest(path=path):
                actual = normalize_jx3api_response("https://www.jx3api.com" + path, {"status": 200, "detail": {}})
                self.assertEqual("success", actual.get("msg"))
                self.assertEqual({}, actual.get("data"))

    async def test_filter_specific_urls_never_share_query_cache_entries(self):
        module = importlib.import_module("src.infra.jx3api_get")
        entries = {}
        cache = Mock()
        cache.get.side_effect = entries.get
        cache.set.side_effect = lambda key, value: entries.__setitem__(key, value)
        async def request(*args, **kwargs):
            return {"status": 200, "detail": {"kungfuName": kwargs["params"]["kungfu"], "equipType": kwargs["params"]["type"]}}
        send = AsyncMock(side_effect=request)
        urls = ["https://www.jx3api.com/calcd/detail?" + urlencode({"kungfu": kungfu, "type": equip_type, "format": "calcd"})
                for kungfu, equip_type in (("云裳心经", "竞技对抗"), ("冰心诀", "秘境挑战"))]
        with patch.object(module, "_cache", cache), patch.object(module.HttpClient, "arequest_json", send):
            for _ in range(2):
                actual = [await module.get(url, server="唯我独尊", name="桃桃白糖") for url in urls]
                self.assertEqual(["云裳心经", "冰心诀"], [row["data"]["kungfuName"] for row in actual])
        self.assertEqual(2, send.await_count)
        self.assertEqual(2, len(entries))


if __name__ == "__main__":
    unittest.main()
