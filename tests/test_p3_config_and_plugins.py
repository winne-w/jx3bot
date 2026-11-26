import ast
import importlib.util
import json
import os
import signal
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from src.infra.runtime_config import (
    CONFIG_SPECS,
    RUNTIME_CONFIG_SPECS,
    ConfigSpec,
    mask_sensitive_value,
    parse_config_value,
    read_runtime_config,
    to_legacy_schema,
    write_runtime_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FinishedSignal(Exception):
    def __init__(self, message: Any = None) -> None:
        super().__init__(str(message))
        self.message = message


class _FakeCommand:
    def __init__(self, name: str = "") -> None:
        self.name = name
        self.handlers: List[Any] = []
        self.finished_messages: List[Any] = []
        self.sent_messages: List[Any] = []

    def handle(self) -> Any:
        def decorator(func: Any) -> Any:
            self.handlers.append(func)
            return func

        return decorator

    async def finish(self, message: Any = None) -> None:
        self.finished_messages.append(message)
        raise _FinishedSignal(message)

    async def send(self, message: Any = None) -> None:
        self.sent_messages.append(message)


class _FakeDriver:
    def on_startup(self, func: Any) -> Any:
        return func

    def on_bot_connect(self, func: Any) -> Any:
        return func


class _FakeGroupEvent:
    def __init__(self, group_id: int = 123456, user_id: int = 10001) -> None:
        self.group_id = group_id
        self.user_id = user_id


class _FakeArgs:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_plain_text(self) -> str:
        return self._text


def _load_config_manager_module() -> Any:
    module_names = [
        "nonebot",
        "nonebot.adapters",
        "nonebot.adapters.onebot",
        "nonebot.adapters.onebot.v11",
        "nonebot.params",
        "config",
        "src.utils.shared_data",
        "config_manager_p3_under_test",
    ]
    originals: Dict[str, Any] = {name: sys.modules.get(name) for name in module_names}

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.on_command = lambda name="", *args, **kwargs: _FakeCommand(name)
    nonebot_mod.get_driver = lambda: _FakeDriver()
    nonebot_mod.logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
    )
    sys.modules["nonebot"] = nonebot_mod

    adapters_mod = types.ModuleType("nonebot.adapters")
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")

    class GroupMessageEvent:
        pass

    class PrivateMessageEvent:
        pass

    class Bot:
        pass

    v11_mod.GroupMessageEvent = GroupMessageEvent
    v11_mod.PrivateMessageEvent = PrivateMessageEvent
    v11_mod.Bot = Bot
    sys.modules["nonebot.adapters"] = adapters_mod
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

    params_mod = types.ModuleType("nonebot.params")
    params_mod.CommandArg = lambda: None
    sys.modules["nonebot.params"] = params_mod

    config_mod = types.ModuleType("config")
    config_mod.ADMIN_QQ = [1]
    sys.modules["config"] = config_mod

    shared_data_mod = types.ModuleType("src.utils.shared_data")
    shared_data_mod.tokendata = None
    sys.modules["src.utils.shared_data"] = shared_data_mod

    module_path = PROJECT_ROOT / "src" / "plugins" / "config_manager.py"
    spec = importlib.util.spec_from_file_location("config_manager_p3_under_test", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load config_manager")
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


def _load_status_monitor_commands_module() -> Tuple[Any, Dict[str, _FakeCommand], Any]:
    pkg_name = "status_monitor_pkg_under_test"
    module_names = [
        "nonebot",
        "nonebot.adapters",
        "nonebot.adapters.onebot",
        "nonebot.adapters.onebot.v11",
        "nonebot.exception",
        "nonebot.params",
        "src.services.jx3.singletons",
        "src.services.jx3.server_status",
        "config",
        pkg_name,
        f"{pkg_name}.jobs",
        f"{pkg_name}.storage",
        f"{pkg_name}.commands",
    ]
    originals: Dict[str, Any] = {name: sys.modules.get(name) for name in module_names}
    registered_commands: Dict[str, _FakeCommand] = {}

    def _fake_on_command(name: str, *args: Any, **kwargs: Any) -> _FakeCommand:
        cmd = _FakeCommand(name)
        registered_commands[name] = cmd
        return cmd

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.on_command = _fake_on_command
    nonebot_mod.on_regex = lambda *args, **kwargs: _FakeCommand()
    nonebot_mod.logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
    )
    sys.modules["nonebot"] = nonebot_mod

    adapters_mod = types.ModuleType("nonebot.adapters")
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Bot = object
    v11_mod.GroupMessageEvent = _FakeGroupEvent
    sys.modules["nonebot.adapters"] = adapters_mod
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

    exc_mod = types.ModuleType("nonebot.exception")
    exc_mod.FinishedException = _FinishedSignal
    sys.modules["nonebot.exception"] = exc_mod

    params_mod = types.ModuleType("nonebot.params")
    params_mod.CommandArg = lambda: None
    sys.modules["nonebot.params"] = params_mod

    class _FakeRepo:
        def __init__(self) -> None:
            self.data: Dict[str, Any] = {}
            self.saved_count = 0

        async def load(self) -> Dict[str, Any]:
            return self.data

        async def save(self, cfg: Dict[str, Any]) -> None:
            self.data = cfg
            self.saved_count += 1

    fake_repo = _FakeRepo()
    singletons_mod = types.ModuleType("src.services.jx3.singletons")
    singletons_mod.group_config_repo = fake_repo
    sys.modules["src.services.jx3.singletons"] = singletons_mod

    server_status_mod = types.ModuleType("src.services.jx3.server_status")
    server_status_mod.select_server_status = lambda *args, **kwargs: None
    sys.modules["src.services.jx3.server_status"] = server_status_mod

    config_mod = types.ModuleType("config")
    config_mod.calendar_URL = ""
    sys.modules["config"] = config_mod

    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(PROJECT_ROOT / "src" / "plugins" / "status_monitor")]
    sys.modules[pkg_name] = pkg_mod

    jobs_mod = types.ModuleType(f"{pkg_name}.jobs")
    for fn_name in (
        "extract_version",
        "format_gte_message",
        "format_time",
        "get_gte_data",
        "get_jx3box_data",
        "get_server_banben",
        "get_server_status",
    ):
        setattr(jobs_mod, fn_name, lambda *args, **kwargs: None)
    sys.modules[f"{pkg_name}.jobs"] = jobs_mod

    storage_mod = types.ModuleType(f"{pkg_name}.storage")
    storage_mod.CacheManager = types.SimpleNamespace(load_cache=lambda *args, **kwargs: {})
    sys.modules[f"{pkg_name}.storage"] = storage_mod

    module_path = PROJECT_ROOT / "src" / "plugins" / "status_monitor" / "commands.py"
    spec = importlib.util.spec_from_file_location(f"{pkg_name}.commands", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load status_monitor.commands")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module, registered_commands, fake_repo


class TestRuntimeConfigRegistry(unittest.TestCase):
    def test_registry_covers_jjc_kungfu_and_identity_keys(self) -> None:
        self.assertIs(CONFIG_SPECS, RUNTIME_CONFIG_SPECS)
        expected_keys = (
            "TOKEN",
            "TICKET",
            "MONGO_URI",
            "SESSION_data",
            "calendar_time",
            "STATUS_check_time",
            "JJC_SYNC_WORKER_COUNT",
            "JJC_SYNC_DISPATCHER_ENABLED",
            "JJC_SYNC_DISPATCHER_IDLE_SLEEP",
            "JJC_SYNC_DISPATCHER_BATCH_SIZE",
            "JJC_SYNC_DISPATCHER_TARGET_PER_WORKER",
            "JJC_KUNGFU_REFRESH_ENABLED",
            "JJC_KUNGFU_REFRESH_SECONDS",
            "JJC_KUNGFU_MAX_STALE_SECONDS",
            "JJC_KUNGFU_TRACK_SECONDS",
            "JJC_RANKING_KUNGFU_CACHE_ENABLED",
            "JJC_ROLE_IDENTITY_RECOVERY_ENABLED",
        )
        for key in expected_keys:
            with self.subTest(key=key):
                self.assertIn(key, RUNTIME_CONFIG_SPECS)
                self.assertIsInstance(RUNTIME_CONFIG_SPECS[key], ConfigSpec)

        legacy = to_legacy_schema()
        for key in expected_keys:
            self.assertIn(key, legacy)
            self.assertNotIn("allow_view", legacy[key])
        self.assertFalse(legacy["MONGO_URI"]["allow_modify"])
        self.assertTrue(legacy["MONGO_URI"]["sensitive"])

    def test_parse_config_value_and_masking(self) -> None:
        for flag_key in (
            "JJC_KUNGFU_REFRESH_ENABLED",
            "JJC_RANKING_KUNGFU_CACHE_ENABLED",
            "JJC_ROLE_IDENTITY_RECOVERY_ENABLED",
        ):
            val, err = parse_config_value(flag_key, "1")
            self.assertEqual(val, 1)
            self.assertIsNone(err)

            val, err = parse_config_value(flag_key, "2")
            self.assertIsNone(val)
            self.assertEqual(err, "配置项值不合法")

        for sec_key in (
            "JJC_KUNGFU_REFRESH_SECONDS",
            "JJC_KUNGFU_MAX_STALE_SECONDS",
            "JJC_KUNGFU_TRACK_SECONDS",
        ):
            val, err = parse_config_value(sec_key, "3600")
            self.assertEqual(val, 3600)
            self.assertIsNone(err)

            val, err = parse_config_value(sec_key, "0")
            self.assertIsNone(val)
            self.assertEqual(err, "配置项值不合法")

        val, err = parse_config_value("JJC_KUNGFU_REFRESH_SECONDS", "abc")
        self.assertIsNone(val)
        self.assertEqual(err, "数值类型配置项需要整数")

        val, err = parse_config_value("NON_EXISTENT_KEY", "1")
        self.assertIsNone(val)
        self.assertIn("未知配置项", err or "")

        self.assertEqual(mask_sensitive_value(None), "未配置")
        self.assertEqual(mask_sensitive_value(""), "未配置")
        self.assertEqual(mask_sensitive_value("abc"), "已配置")
        self.assertEqual(mask_sensitive_value("secret_token"), "sec***")

    def test_read_and_write_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "runtime_config.json"
            self.assertEqual(read_runtime_config(cfg_path), {})

            write_res = write_runtime_config(cfg_path, {"JJC_KUNGFU_REFRESH_ENABLED": 1})
            self.assertIs(write_res, True)
            self.assertEqual(read_runtime_config(cfg_path), {"JJC_KUNGFU_REFRESH_ENABLED": 1})


class TestConfigManagerGracefulRestart(unittest.IsolatedAsyncioTestCase):
    def test_source_has_no_shell_true_or_os_exit(self) -> None:
        source = (PROJECT_ROOT / "src" / "plugins" / "config_manager.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os._exit", source)

    async def test_default_restart_sends_sigterm_without_popen(self) -> None:
        module = _load_config_manager_module()
        with tempfile.TemporaryDirectory() as tmp_dir:
            flag_path = Path(tmp_dir) / "restart_info.json"
            module.RESTART_FLAG_FILE = str(flag_path)

            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("JX3BOT_SELF_SPAWN_RESTART", None)
                with mock.patch.object(module.asyncio, "sleep", new=mock.AsyncMock()), \
                     mock.patch.object(module.subprocess, "Popen") as mock_popen, \
                     mock.patch.object(module.os, "kill") as mock_kill, \
                     mock.patch.object(module.sys, "platform", "linux"):
                    await module.restart_bot(group_id=100, user_id=200, reason="测试重启")

            mock_popen.assert_not_called()
            mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
            saved = json.loads(flag_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["group_id"], 100)
            self.assertEqual(saved["user_id"], 200)
            self.assertEqual(saved["reason"], "测试重启")

    async def test_self_spawn_restart_uses_list_argv_without_shell(self) -> None:
        module = _load_config_manager_module()
        with tempfile.TemporaryDirectory() as tmp_dir:
            flag_path = Path(tmp_dir) / "restart_info.json"
            module.RESTART_FLAG_FILE = str(flag_path)

            with mock.patch.dict(os.environ, {"JX3BOT_SELF_SPAWN_RESTART": "1"}, clear=False):
                with mock.patch.object(module.asyncio, "sleep", new=mock.AsyncMock()), \
                     mock.patch.object(module.subprocess, "Popen") as mock_popen, \
                     mock.patch.object(module.os, "kill") as mock_kill, \
                     mock.patch.object(module.sys, "platform", "linux"):
                    await module.restart_bot(reason="自拉起重启")

            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertIsInstance(args[0], list)
            self.assertEqual(args[0][0], sys.executable)
            self.assertNotIn("shell", kwargs)
            mock_kill.assert_called_once_with(os.getpid(), signal.SIGTERM)


class TestStatusMonitorPushToggles(unittest.IsolatedAsyncioTestCase):
    def test_normalize_group_entry_legacy_formats(self) -> None:
        module, _, _ = _load_status_monitor_commands_module()

        from_list = module._normalize_group_entry(["梦江南"], "开服推送")
        self.assertEqual(from_list, {"servers": ["梦江南"], "开服推送": True})

        from_list_jjc = module._normalize_group_entry(["梦江南"], "竞技排名推送")
        self.assertEqual(from_list_jjc, {"servers": ["梦江南"], "竞技排名推送": False})

        from_legacy_dict = module._normalize_group_entry(
            {"梦江南": True, "新闻推送": False},
            "开服推送",
        )
        self.assertEqual(from_legacy_dict["servers"], ["梦江南"])
        self.assertIs(from_legacy_dict["开服推送"], True)
        self.assertIs(from_legacy_dict["新闻推送"], False)

        from_std_dict = module._normalize_group_entry({"servers": "梦江南"}, "竞技排名推送")
        self.assertEqual(from_std_dict, {"servers": "梦江南", "竞技排名推送": False})

    async def test_all_six_push_toggles_registered_without_name_collision(self) -> None:
        module, registered, fake_repo = _load_status_monitor_commands_module()

        expected_commands = (
            ("kftoggle_cmd", "开服推送"),
            ("xwtoggle_cmd", "新闻推送"),
            ("fltoggle_cmd", "福利推送"),
            ("jgtoggle_cmd", "技改推送"),
            ("rctoggle_cmd", "日常推送"),
            ("jjctoggle_cmd", "竞技排名推送"),
        )
        seen_cmds = set()
        for attr_name, cmd_name in expected_commands:
            cmd = getattr(module, attr_name)
            self.assertIs(cmd, registered[cmd_name])
            self.assertNotIn(id(cmd), seen_cmds)
            seen_cmds.add(id(cmd))

        # Verify news toggle and welfare toggle operate independently on legacy list entry
        fake_repo.data = {"999": ["梦江南"]}
        news_handler = module.xwtoggle_cmd.handlers[0]
        with self.assertRaises(_FinishedSignal) as news_ctx:
            await news_handler(_FakeGroupEvent(group_id=999), args=_FakeArgs("关闭"))
        self.assertEqual(news_ctx.exception.message, "已关闭本群新闻推送功能")
        self.assertEqual(fake_repo.data["999"], {"servers": ["梦江南"], "新闻推送": False})

        welfare_handler = module.fltoggle_cmd.handlers[0]
        with self.assertRaises(_FinishedSignal) as welfare_ctx:
            await welfare_handler(_FakeGroupEvent(group_id=999), args=_FakeArgs("开启"))
        self.assertEqual(welfare_ctx.exception.message, "已开启本群福利推送功能")
        self.assertIs(fake_repo.data["999"]["福利推送"], True)
        self.assertIs(fake_repo.data["999"]["新闻推送"], False)


class TestWanbaolouAliasNoPrint(unittest.TestCase):
    def test_alias_module_has_zero_print_calls(self) -> None:
        alias_path = PROJECT_ROOT / "src" / "plugins" / "wanbaolou" / "alias.py"
        source = alias_path.read_text(encoding="utf-8")
        self.assertEqual(source.count("print("), 0)

        tree = ast.parse(source, filename=str(alias_path))
        print_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        self.assertEqual(len(print_calls), 0)


if __name__ == "__main__":
    unittest.main()
