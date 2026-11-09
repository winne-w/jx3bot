import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List


class _FakeService:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.dispatcher_calls: List[Dict[str, Any]] = []
        self.started = asyncio.Event()
        self.dispatcher_started = asyncio.Event()

    async def run_worker(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        self.started.set()
        await asyncio.Event().wait()
        return {"error": False}

    async def run_dispatcher(self, **kwargs: Any) -> Dict[str, Any]:
        self.dispatcher_calls.append(kwargs)
        self.dispatcher_started.set()
        await asyncio.Event().wait()
        return {"error": False}


def _load_runtime(worker_count: int, service: Any, dispatcher_enabled: int = 1) -> Any:
    originals: Dict[str, Any] = {}
    for name in ("config", "src.services.jx3.singletons", "jjc_sync_worker_runtime_under_test"):
        originals[name] = sys.modules.get(name)

    config_mod = types.ModuleType("config")
    config_mod.JJC_SYNC_WORKER_COUNT = worker_count
    config_mod.JJC_SYNC_DISPATCHER_ENABLED = dispatcher_enabled
    sys.modules["config"] = config_mod

    singletons_mod = types.ModuleType("src.services.jx3.singletons")
    singletons_mod.jjc_match_data_sync_service = service
    sys.modules["src.services.jx3.singletons"] = singletons_mod

    module_path = Path(__file__).resolve().parents[1] / "src" / "services" / "jx3" / "jjc_sync_worker_runtime.py"
    spec = importlib.util.spec_from_file_location("jjc_sync_worker_runtime_under_test", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load runtime module")
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


class TestJjcSyncWorkerRuntime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._runtime_modules: List[Any] = []

    async def asyncTearDown(self) -> None:
        for module in reversed(self._runtime_modules):
            await module.stop_jjc_sync_dispatcher()
            await module.stop_jjc_sync_workers()

    def _load_runtime(self, worker_count: int, service: Any, dispatcher_enabled: int = 1) -> Any:
        module = _load_runtime(worker_count, service, dispatcher_enabled=dispatcher_enabled)
        self._runtime_modules.append(module)
        return module

    async def test_zero_worker_count_does_not_create_tasks(self) -> None:
        service = _FakeService()
        module = self._load_runtime(0, service)

        await module.start_jjc_sync_workers()

        self.assertEqual(module._TASKS, [])
        self.assertEqual(service.calls, [])

    async def test_negative_worker_count_does_not_create_tasks(self) -> None:
        service = _FakeService()
        module = self._load_runtime(-1, service)

        await module.start_jjc_sync_workers()

        self.assertEqual(module._TASKS, [])
        self.assertEqual(service.calls, [])

    async def test_dispatcher_disabled_does_not_create_tasks(self) -> None:
        service = _FakeService()
        module = self._load_runtime(1, service, dispatcher_enabled=0)

        await module.start_jjc_sync_dispatcher()

        self.assertEqual(module._DISPATCHER_TASKS, [])
        self.assertEqual(service.dispatcher_calls, [])

    async def test_starts_configured_workers_with_bot_worker_ids(self) -> None:
        service = _FakeService()
        module = self._load_runtime(2, service)

        await module.start_jjc_sync_workers()
        await asyncio.wait_for(service.started.wait(), timeout=1)
        await asyncio.sleep(0)

        self.assertEqual(len(module._TASKS), 2)
        self.assertEqual(len(service.calls), 2)
        worker_ids = [call["worker_id"] for call in service.calls]
        self.assertEqual(len(set(worker_ids)), 2)
        self.assertTrue(all(worker_id.startswith("bot:") for worker_id in worker_ids))
        self.assertTrue(worker_ids[0].endswith(":0"))
        self.assertTrue(worker_ids[1].endswith(":1"))
        self.assertEqual(len(worker_ids[0].split(":")), 3)
        self.assertEqual(
            service.calls[0],
            {"mode": "full", "worker_id": worker_ids[0]},
        )

        tasks = list(module._TASKS)
        await module.stop_jjc_sync_workers()
        self.assertEqual(module._TASKS, [])
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(task.done() for task in tasks))
        self.assertTrue(all(task.cancelled() for task in tasks))

    async def test_starts_dispatcher_task(self) -> None:
        service = _FakeService()
        module = self._load_runtime(1, service, dispatcher_enabled=1)

        await module.start_jjc_sync_dispatcher()
        await asyncio.wait_for(service.dispatcher_started.wait(), timeout=1)
        await asyncio.sleep(0)

        self.assertEqual(len(module._DISPATCHER_TASKS), 1)
        self.assertEqual(service.dispatcher_calls, [{}])

        task = module._DISPATCHER_TASKS[0]
        await module.stop_jjc_sync_dispatcher()

        self.assertEqual(module._DISPATCHER_TASKS, [])
        self.assertTrue(task.done())
        self.assertTrue(task.cancelled())

    async def test_worker_exception_is_caught(self) -> None:
        class FailingService:
            def __init__(self) -> None:
                self.calls = 0

            async def run_worker(self, **kwargs: Any) -> None:
                self.calls += 1
                raise RuntimeError("boom")

        service = FailingService()
        module = self._load_runtime(1, service)

        await module.start_jjc_sync_workers()
        await asyncio.sleep(0)

        self.assertEqual(service.calls, 1)
        self.assertTrue(module._TASKS[0].done())
        self.assertIsNone(module._TASKS[0].exception())

    async def test_stop_cancels_running_tasks(self) -> None:
        service = _FakeService()
        module = self._load_runtime(1, service)

        await module.start_jjc_sync_workers()
        await asyncio.wait_for(service.started.wait(), timeout=1)
        task = module._TASKS[0]
        await module.stop_jjc_sync_workers()

        self.assertTrue(task.cancelled())
        self.assertEqual(module._TASKS, [])


if __name__ == "__main__":
    unittest.main()
