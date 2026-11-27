import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List


class _FinishedSignal(Exception):
    def __init__(self, message: Any = None) -> None:
        super().__init__(str(message))
        self.message = message


class _FakeCommand:
    def __init__(self) -> None:
        self.finished_messages: List[Any] = []
        self.sent_messages: List[Any] = []

    def handle(self) -> Any:
        def decorator(func: Any) -> Any:
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


def _load_config_manager() -> Any:
    module_names = [
        "nonebot",
        "nonebot.adapters",
        "nonebot.adapters.onebot",
        "nonebot.adapters.onebot.v11",
        "nonebot.params",
        "config",
        "src.utils.shared_data",
        "config_manager_under_test",
    ]
    originals: Dict[str, Any] = {name: sys.modules.get(name) for name in module_names}

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.on_command = lambda *args, **kwargs: _FakeCommand()
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
    config_mod.JJC_SYNC_WORKER_COUNT = 0
    config_mod.JJC_SYNC_DISPATCHER_ENABLED = 1
    config_mod.JJC_SYNC_DISPATCHER_IDLE_SLEEP = 10
    config_mod.JJC_SYNC_DISPATCHER_BATCH_SIZE = 20
    config_mod.JJC_SYNC_DISPATCHER_TARGET_PER_WORKER = 3
    config_mod.MONGO_URI = "mongodb://user:password@localhost:27017/jx3bot"
    sys.modules["config"] = config_mod

    shared_data_mod = types.ModuleType("src.utils.shared_data")
    shared_data_mod.tokendata = None
    sys.modules["src.utils.shared_data"] = shared_data_mod

    module_path = Path(__file__).resolve().parents[1] / "src" / "plugins" / "config_manager.py"
    spec = importlib.util.spec_from_file_location("config_manager_under_test", str(module_path))
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


class TestConfigManagerSchema(unittest.TestCase):
    def test_worker_count_is_modifiable_and_validated(self) -> None:
        module = _load_config_manager()

        self.assertIn("JJC_SYNC_WORKER_COUNT", module._modifiable_config_keys())
        value, error = module._parse_config_value("JJC_SYNC_WORKER_COUNT", "1")
        self.assertEqual(value, 1)
        self.assertIsNone(error)

        value, error = module._parse_config_value("JJC_SYNC_WORKER_COUNT", "-1")
        self.assertIsNone(value)
        self.assertEqual(error, "配置项值不合法")

    def test_dispatcher_config_keys_are_modifiable_and_validated(self) -> None:
        module = _load_config_manager()

        self.assertIn("JJC_SYNC_DISPATCHER_ENABLED", module._modifiable_config_keys())
        value, error = module._parse_config_value("JJC_SYNC_DISPATCHER_ENABLED", "1")
        self.assertEqual(value, 1)
        self.assertIsNone(error)
        value, error = module._parse_config_value("JJC_SYNC_DISPATCHER_ENABLED", "2")
        self.assertIsNone(value)
        self.assertEqual(error, "配置项值不合法")

        for key in (
            "JJC_SYNC_DISPATCHER_IDLE_SLEEP",
            "JJC_SYNC_DISPATCHER_BATCH_SIZE",
            "JJC_SYNC_DISPATCHER_TARGET_PER_WORKER",
        ):
            with self.subTest(key=key):
                self.assertIn(key, module._modifiable_config_keys())
                value, error = module._parse_config_value(key, "1")
                self.assertEqual(value, 1)
                self.assertIsNone(error)
                value, error = module._parse_config_value(key, "0")
                self.assertIsNone(value)
                self.assertEqual(error, "配置项值不合法")

    def test_mongo_uri_is_viewable_sensitive_and_not_modifiable(self) -> None:
        module = _load_config_manager()

        schema = module.CONFIG_SCHEMA["MONGO_URI"]
        self.assertNotIn("allow_view", schema)
        self.assertTrue(schema["sensitive"])
        self.assertFalse(schema["allow_modify"])
        self.assertNotIn("MONGO_URI", module._modifiable_config_keys())

    def test_sensitive_values_are_masked(self) -> None:
        module = _load_config_manager()

        self.assertEqual(module._mask_sensitive_value(""), "未配置")
        self.assertEqual(module._mask_sensitive_value("abcdef"), "abc***")

    def test_view_config_uses_config_defaults_when_runtime_config_is_empty(self) -> None:
        module = _load_config_manager()

        text = module._build_view_config_text({})

        self.assertIn("JJC_SYNC_WORKER_COUNT = 0", text)
        self.assertIn("JJC_SYNC_DISPATCHER_ENABLED = 1", text)

    def test_view_config_masks_mongo_uri_from_config_module(self) -> None:
        module = _load_config_manager()

        text = module._build_view_config_text({})

        self.assertIn("MONGO_URI = mon***", text)
        self.assertNotIn("mongodb://user:password@localhost:27017/jx3bot", text)


class _FakeEvent:
    def __init__(self, user_id: str = "1") -> None:
        self._user_id = user_id

    def get_user_id(self) -> str:
        return self._user_id


class _FakeArgs:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_plain_text(self) -> str:
        return self._text


class TestConfigManagerReadErrors(unittest.IsolatedAsyncioTestCase):
    async def test_corrupted_json_returns_error_in_view_and_modify(self) -> None:
        module = _load_config_manager()
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "runtime_config.json"
            config_path.write_text("{invalid json", encoding="utf-8")
            module.CONFIG_FILE = str(config_path)

            read_result = module.read_config_file()
            self.assertIsInstance(read_result, str)
            self.assertTrue(read_result.startswith("读取配置文件失败:"))

            with self.assertRaises(_FinishedSignal) as view_ctx:
                await module.handle_view_config(_FakeEvent("1"))
            self.assertTrue(str(view_ctx.exception.message).startswith("读取配置文件失败:"))

            with self.assertRaises(_FinishedSignal) as mod_ctx:
                await module.handle_config(_FakeEvent("1"), args=_FakeArgs("SESSION_data=600"))
            self.assertTrue(str(mod_ctx.exception.message).startswith("读取配置文件失败:"))

    async def test_non_dict_top_level_json_returns_error_in_view_and_modify(self) -> None:
        module = _load_config_manager()
        for raw_json in ("[1, 2, 3]", "123", '"hello"'):
            with self.subTest(raw_json=raw_json):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    config_path = Path(tmp_dir) / "runtime_config.json"
                    config_path.write_text(raw_json, encoding="utf-8")
                    module.CONFIG_FILE = str(config_path)

                    read_result = module.read_config_file()
                    self.assertEqual(read_result, "读取配置文件失败: 配置文件顶层必须是 JSON 对象")

                    with self.assertRaises(_FinishedSignal) as view_ctx:
                        await module.handle_view_config(_FakeEvent("1"))
                    self.assertEqual(
                        view_ctx.exception.message,
                        "读取配置文件失败: 配置文件顶层必须是 JSON 对象",
                    )

                    with self.assertRaises(_FinishedSignal) as mod_ctx:
                        await module.handle_config(
                            _FakeEvent("1"),
                            args=_FakeArgs("SESSION_data=600"),
                        )
                    self.assertEqual(
                        mod_ctx.exception.message,
                        "读取配置文件失败: 配置文件顶层必须是 JSON 对象",
                    )


if __name__ == "__main__":
    unittest.main()
