import contextlib
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List


def _load_cli_module() -> Any:
    originals: Dict[str, Any] = {}
    for name in ("config", "src.infra.mongo", "src.services.jx3.singletons"):
        originals[name] = sys.modules.get(name)

    config_mod = types.ModuleType("config")
    config_mod.MONGO_URI = "mongodb://example"
    sys.modules["config"] = config_mod

    mongo_mod = types.ModuleType("src.infra.mongo")

    async def init_mongo(uri: str) -> None:
        return None

    mongo_mod.init_mongo = init_mongo
    sys.modules["src.infra.mongo"] = mongo_mod

    singletons_mod = types.ModuleType("src.services.jx3.singletons")
    singletons_mod.jjc_match_data_sync_service = object()
    sys.modules["src.services.jx3.singletons"] = singletons_mod

    module_path = Path(__file__).resolve().parents[1] / "scripts" / "jjc_sync.py"
    spec = importlib.util.spec_from_file_location("jjc_sync_cli_under_test", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load jjc_sync cli module")
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


class _FakeService:
    def __init__(self) -> None:
        self.worker_calls: List[Dict[str, Any]] = []

    async def run_worker(self, **kwargs: Any) -> Dict[str, Any]:
        self.worker_calls.append(kwargs)
        return {
            "error": False,
            "worker_id": kwargs.get("worker_id") or "worker-1",
            "stopped_reason": "test",
            "processed_roles": 0,
            "idle_ticks": 0,
            "paused_ticks": 0,
            "elapsed_seconds": 0.0,
        }

    async def status(self) -> Dict[str, Any]:
        return {
            "error": False,
            "paused": False,
            "pause_reason": "",
            "counts": {"queued": 2},
            "recent_errors": [],
            "worker_running": False,
            "workers": [
                {
                    "worker_id": "worker-old",
                    "status": "idle",
                    "effective_status": "offline",
                    "online": False,
                }
            ],
        }


class TestJjcSyncCli(unittest.IsolatedAsyncioTestCase):
    async def test_start_parser_accepts_legacy_limit(self) -> None:
        module = _load_cli_module()

        args = module.build_parser().parse_args(["start", "--limit=0"])

        self.assertEqual(args.command, "start")
        self.assertEqual(args.limit, 0)
        self.assertIsNone(args.max_roles)

    async def test_start_help_documents_zero_limit_as_unlimited(self) -> None:
        module = _load_cli_module()
        parser = module.build_parser()
        subparsers_action = next(action for action in parser._actions if getattr(action, "choices", None))
        start_parser = subparsers_action.choices["start"]

        help_text = start_parser.format_help()

        self.assertIn("0 或不传表示不限数量", help_text)
        self.assertIn("--minutes", help_text)
        self.assertIn("--worker-id", help_text)

    async def test_cmd_worker_passes_zero_legacy_limit_to_service(self) -> None:
        module = _load_cli_module()
        fake_service = _FakeService()
        module.svc = fake_service
        args = SimpleNamespace(
            mode="incremental_or_full",
            minutes=0,
            idle_sleep=1,
            max_roles=None,
            limit=0,
            worker_id="worker-test",
        )

        with contextlib.redirect_stdout(io.StringIO()):
            await module.cmd_worker(args)

        self.assertEqual(fake_service.worker_calls[0]["max_roles"], 0)

    async def test_cmd_worker_prefers_explicit_max_roles_over_legacy_limit(self) -> None:
        module = _load_cli_module()
        fake_service = _FakeService()
        module.svc = fake_service
        args = SimpleNamespace(
            mode="incremental_or_full",
            minutes=0,
            idle_sleep=1,
            max_roles=5,
            limit=0,
            worker_id="worker-test",
        )

        with contextlib.redirect_stdout(io.StringIO()):
            await module.cmd_worker(args)

        self.assertEqual(fake_service.worker_calls[0]["max_roles"], 5)

    async def test_cmd_status_prints_heartbeat_aware_worker_state(self) -> None:
        module = _load_cli_module()
        fake_service = _FakeService()
        module.svc = fake_service

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            await module.cmd_status(SimpleNamespace())

        text = output.getvalue()
        self.assertIn("worker: 无活跃 worker", text)
        self.assertIn("worker-old: offline", text)


if __name__ == "__main__":
    unittest.main()
