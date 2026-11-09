import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class TestLiveRuntime(unittest.IsolatedAsyncioTestCase):
    def runtime(self, service, secret='test-secret'):
        config = types.ModuleType('config')
        config.JJC_LIVE_SOURCE_SECRET = secret
        singleton = types.ModuleType('src.services.jx3.singletons')
        singleton.jjc_live_refresh_service = service
        path = Path(__file__).resolve().parents[1] / 'src/services/jx3/jjc_live_refresh_runtime.py'
        spec = importlib.util.spec_from_file_location('live_runtime_under_test', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'config': config}):
            spec.loader.exec_module(module)
        return module, singleton

    def service(self):
        started = asyncio.Event()
        async def worker():
            started.set()
            await asyncio.Event().wait()
        service = types.SimpleNamespace(enabled=lambda: True, readiness=AsyncMock(return_value={'state':'ready'}),
            repo=types.SimpleNamespace(initialize=AsyncMock()), run_worker=worker)
        return service, started

    async def test_start_is_idempotent_and_stop_cancels_worker(self):
        service, started = self.service()
        module, singleton = self.runtime(service)
        with patch.dict(sys.modules, {'src.services.jx3.singletons': singleton}):
            await module.start_live_refresh()
            task = module._task
            try:
                await asyncio.wait_for(started.wait(), 1)
                await module.start_live_refresh()
                self.assertIs(task, module._task)
                service.repo.initialize.assert_awaited_once()
            finally:
                await module.stop_live_refresh()
            self.assertIsNone(module._task)
            self.assertTrue(task.cancelled())

    async def test_missing_secret_does_not_start_worker(self):
        service, _ = self.service()
        module, singleton = self.runtime(service, '')
        with patch.dict(sys.modules, {'src.services.jx3.singletons': singleton}):
            await module.start_live_refresh()
        self.assertIsNone(module._task)
        service.repo.initialize.assert_not_called()

    async def test_optional_worker_initialization_failure_does_not_abort_bot_startup(self):
        service, _ = self.service()
        service.repo.initialize.side_effect = RuntimeError('isolated index failure')
        module, singleton = self.runtime(service)
        with patch.dict(sys.modules, {'src.services.jx3.singletons': singleton}):
            await module.start_live_refresh()
        self.assertIsNone(module._task)

    async def test_readiness_failure_does_not_abort_bot_startup(self):
        service, _ = self.service()
        service.readiness.side_effect = RuntimeError('isolated readiness failure')
        module, singleton = self.runtime(service)
        with patch.dict(sys.modules, {'src.services.jx3.singletons': singleton}):
            await module.start_live_refresh()
        self.assertIsNone(module._task)
