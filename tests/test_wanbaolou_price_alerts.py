from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]


class _FakeMatcher:
    def handle(self) -> Any:
        def _decorator(func: Any) -> Any:
            return func

        return _decorator


class _FakeDriver:
    def on_bot_connect(self, func: Any) -> Any:
        return func

    def on_startup(self, func: Any) -> Any:
        return func


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: List[tuple[tuple[Any, ...], Dict[str, Any]]] = []

    def add_job(self, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((args, kwargs))


class _FakeLogger:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error(self, *args: Any, **kwargs: Any) -> None:
        pass

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass


def _load_wanbaolou_module() -> tuple[Any, _FakeScheduler]:
    fake_scheduler = _FakeScheduler()
    module_names = [
        "nonebot",
        "nonebot.adapters",
        "nonebot.adapters.onebot",
        "nonebot.adapters.onebot.v11",
        "nonebot.plugin",
        "nonebot.params",
        "nonebot.exception",
        "nonebot.log",
        "nonebot.rule",
        "nonebot.matcher",
        "src.infra.group_delivery",
        "src.infra.screenshot",
        "src.infra.mongo",
        "src.utils.random_text",
        "src.utils.shared_data",
        "src.services.jx3.singletons",
        "src.storage.mongo_repos.wanbaolou_sub_repo",
        "src.plugins.wanbaolou",
        "src.plugins.wanbaolou.api",
        "src.plugins.wanbaolou.config",
        "src.plugins.wanbaolou.utils",
        "src.plugins.wanbaolou.alias",
        "src.plugins.wanbaolou.searcher",
        "config",
    ]
    originals: Dict[str, Any] = {name: sys.modules.get(name) for name in module_names}

    try:
        nonebot_mod = types.ModuleType("nonebot")
        nonebot_mod.get_driver = lambda: _FakeDriver()
        nonebot_mod.on_regex = lambda *a, **kw: _FakeMatcher()
        nonebot_mod.on_command = lambda *a, **kw: _FakeMatcher()
        nonebot_mod.require = lambda _name: types.SimpleNamespace(scheduler=fake_scheduler)
        sys.modules["nonebot"] = nonebot_mod

        adapters_mod = types.ModuleType("nonebot.adapters")
        onebot_mod = types.ModuleType("nonebot.adapters.onebot")
        v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
        v11_mod.Bot = object
        v11_mod.Event = object
        v11_mod.Message = lambda x="": x
        v11_mod.MessageSegment = types.SimpleNamespace(at=lambda uid: f"[at:{uid}]", image=lambda x: x)
        sys.modules["nonebot.adapters"] = adapters_mod
        sys.modules["nonebot.adapters.onebot"] = onebot_mod
        sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

        plugin_mod = types.ModuleType("nonebot.plugin")
        plugin_mod.PluginMetadata = lambda **kw: types.SimpleNamespace(**kw)
        sys.modules["nonebot.plugin"] = plugin_mod

        params_mod = types.ModuleType("nonebot.params")
        params_mod.RegexGroup = lambda: ()
        sys.modules["nonebot.params"] = params_mod

        exc_mod = types.ModuleType("nonebot.exception")
        exc_mod.FinishedException = type("FinishedException", (Exception,), {})
        sys.modules["nonebot.exception"] = exc_mod

        log_mod = types.ModuleType("nonebot.log")
        log_mod.logger = _FakeLogger()
        sys.modules["nonebot.log"] = log_mod

        rule_mod = types.ModuleType("nonebot.rule")
        rule_mod.Rule = lambda *a, **kw: None
        sys.modules["nonebot.rule"] = rule_mod

        matcher_mod = types.ModuleType("nonebot.matcher")
        matcher_mod.Matcher = object
        sys.modules["nonebot.matcher"] = matcher_mod

        group_delivery_mod = types.ModuleType("src.infra.group_delivery")
        group_delivery_mod.send_group_msg = AsyncMock()
        sys.modules["src.infra.group_delivery"] = group_delivery_mod

        screenshot_mod = types.ModuleType("src.infra.screenshot")
        screenshot_mod.jietu = AsyncMock()
        sys.modules["src.infra.screenshot"] = screenshot_mod

        mongo_mod = types.ModuleType("src.infra.mongo")
        mongo_mod.get_db = lambda: None
        sys.modules["src.infra.mongo"] = mongo_mod

        random_text_mod = types.ModuleType("src.utils.random_text")
        random_text_mod.suijitext = lambda: ""
        sys.modules["src.utils.random_text"] = random_text_mod

        shared_data_mod = types.ModuleType("src.utils.shared_data")
        shared_data_mod.SEARCH_RESULTS = {}
        shared_data_mod.user_sessions = {}
        sys.modules["src.utils.shared_data"] = shared_data_mod

        singletons_mod = types.ModuleType("src.services.jx3.singletons")
        singletons_mod.jinja_env = object()
        sys.modules["src.services.jx3.singletons"] = singletons_mod

        sub_repo_mod = types.ModuleType("src.storage.mongo_repos.wanbaolou_sub_repo")
        sub_repo_mod.WanbaolouSubRepo = object
        sys.modules["src.storage.mongo_repos.wanbaolou_sub_repo"] = sub_repo_mod

        config_mod = types.ModuleType("config")
        config_mod.wanbaolou = 50
        sys.modules["config"] = config_mod

        wbl_api_mod = types.ModuleType("src.plugins.wanbaolou.api")

        class _DummyAPI:
            def __init__(self, verify_ssl: bool = False) -> None:
                self.verify_ssl = verify_ssl
                self.get_item_list = AsyncMock()

        wbl_api_mod.JX3TradeAPI = _DummyAPI
        wbl_api_mod.api = _DummyAPI()
        wbl_api_mod.search_jx3_appearances = AsyncMock()
        sys.modules["src.plugins.wanbaolou.api"] = wbl_api_mod

        wbl_cfg_mod = types.ModuleType("src.plugins.wanbaolou.config")
        wbl_cfg_mod.config = types.SimpleNamespace()
        sys.modules["src.plugins.wanbaolou.config"] = wbl_cfg_mod

        wbl_utils_mod = types.ModuleType("src.plugins.wanbaolou.utils")
        wbl_utils_mod.format_time_string = lambda x: str(x)
        wbl_utils_mod.save_image_cache = AsyncMock()
        sys.modules["src.plugins.wanbaolou.utils"] = wbl_utils_mod

        wbl_alias_mod = types.ModuleType("src.plugins.wanbaolou.alias")
        wbl_alias_mod.setup_alias_refresh_job = AsyncMock()
        sys.modules["src.plugins.wanbaolou.alias"] = wbl_alias_mod

        wbl_searcher_mod = types.ModuleType("src.plugins.wanbaolou.searcher")
        wbl_searcher_mod.init_appearance_searcher = AsyncMock()
        wbl_searcher_mod.search_appearance = AsyncMock()
        sys.modules["src.plugins.wanbaolou.searcher"] = wbl_searcher_mod

        module_path = ROOT / "src" / "plugins" / "wanbaolou" / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "src.plugins.wanbaolou",
            str(module_path),
            submodule_search_locations=[str(module_path.parent)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("failed to load wanbaolou plugin")
        module = importlib.util.module_from_spec(spec)
        sys.modules["src.plugins.wanbaolou"] = module
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module, fake_scheduler


class WanbaolouPriceAlertsTests(unittest.TestCase):
    def test_check_price_alerts_deduplicates_item_queries_and_isolates_errors(self) -> None:
        module, _ = _load_wanbaolou_module()
        fake_bot = types.SimpleNamespace(send_private_msg=AsyncMock())
        module._bot = fake_bot
        module.send_group_msg = AsyncMock()

        repo = types.SimpleNamespace(
            all=AsyncMock(
                return_value=[
                    {"item_name": "红发", "price_threshold": 500, "user_id": "101", "group_id": "2001"},
                    {"item_name": " 红发 ", "price_threshold": 450, "user_id": "102", "group_id": None},
                    {"item_name": "红发", "price_threshold": 300, "user_id": "109", "group_id": None},
                    {"item_name": "异常外观", "price_threshold": 100, "user_id": "103", "group_id": None},
                    {"item_name": "异常外观", "price_threshold": 200, "user_id": "104", "group_id": None},
                    {"item_name": "白发", "price_threshold": 800, "user_id": "105", "group_id": None},
                    {"item_name": "   ", "price_threshold": 800, "user_id": "106", "group_id": None},
                    {"item_name": None, "price_threshold": 800, "user_id": "107", "group_id": None},
                    {"item_name": 123, "price_threshold": 800, "user_id": "108", "group_id": None},
                ]
            ),
            remove=AsyncMock(),
        )
        module._repo = lambda: repo

        async def _fake_get_item_list(**kwargs: Any) -> Any:
            name = kwargs["item_name"]
            if name == "异常外观":
                raise RuntimeError("upstream timeout")
            if name == "红发":
                return {"parsed_items": [{"price": 400}]}
            if name == "白发":
                return {"parsed_items": [{"price": 750}]}
            return None

        module.api.get_item_list = AsyncMock(side_effect=_fake_get_item_list)

        asyncio.run(module.check_price_alerts())

        queried_names = [call.kwargs["item_name"] for call in module.api.get_item_list.await_args_list]
        self.assertEqual(queried_names, ["红发", "异常外观", "白发"])

        # 用户 101 群聊触发；用户 102（带空格原始 item_name）私聊触发并按原始键删除；用户 109 未达阈值不触发；用户 105 私聊触发
        self.assertEqual(module.send_group_msg.await_count, 1)
        self.assertEqual(module.send_group_msg.await_args_list[0].kwargs["group_id"], 2001)
        self.assertEqual(fake_bot.send_private_msg.await_count, 2)
        private_user_ids = [call.kwargs["user_id"] for call in fake_bot.send_private_msg.await_args_list]
        self.assertEqual(private_user_ids, [102, 105])
        removed_pairs = [call.args for call in repo.remove.await_args_list]
        self.assertEqual(removed_pairs, [("101", "红发"), ("102", " 红发 "), ("105", "白发")])

    def test_init_subscription_system_registers_hardened_job_options(self) -> None:
        module, fake_scheduler = _load_wanbaolou_module()
        asyncio.run(module.init_subscription_system())
        self.assertEqual(len(fake_scheduler.jobs), 1)
        args, kwargs = fake_scheduler.jobs[0]
        self.assertIs(args[0], module.check_price_alerts)
        self.assertEqual(args[1], "interval")
        self.assertEqual(kwargs["id"], "wanbaolou_price_alerts")
        self.assertTrue(kwargs["replace_existing"])
        self.assertEqual(kwargs["max_instances"], 1)

    def test_alias_refresh_job_declares_max_instances_one(self) -> None:
        alias_path = ROOT / "src" / "plugins" / "wanbaolou" / "alias.py"
        tree = ast.parse(alias_path.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_job"
            ):
                keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
                if "id" in keywords and ast.literal_eval(keywords["id"]) == "wanbaolou_alias_refresh":
                    found = True
                    self.assertEqual(ast.literal_eval(keywords["max_instances"]), 1)
                    self.assertTrue(ast.literal_eval(keywords["replace_existing"]))
        self.assertTrue(found, "wanbaolou_alias_refresh add_job call not found")


if __name__ == "__main__":
    unittest.main()
