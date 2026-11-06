"""The optional local worker has no QQ or distributed scheduler dependency."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import src.services.jx3.jjc_kungfu_refresh_runtime as runtime
from src.storage.mongo_repos.jjc_kungfu_refresh_repo import QueueIntegrityError


class KungfuRefreshRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await runtime.stop_kungfu_refresh()

    def service(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def run_once():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        service = SimpleNamespace(initialize=AsyncMock(), run_once=AsyncMock(side_effect=run_once))
        return service, started, cancelled

    async def test_start_is_idempotent_stop_cancels_inflight_work_without_qq(self):
        service, started, cancelled = self.service()
        with patch.object(runtime.cfg, "JJC_KUNGFU_REFRESH_ENABLED", 1, create=True):
            await runtime.start_kungfu_refresh(service)
            await asyncio.wait_for(started.wait(), 1)
            task = runtime._task
            await runtime.start_kungfu_refresh(service)
            self.assertIs(task, runtime._task)
            service.initialize.assert_awaited_once()
            await runtime.stop_kungfu_refresh()
        self.assertTrue(task.cancelled())
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(runtime._task)
        await runtime.stop_kungfu_refresh()

    async def test_concurrent_start_only_initializes_and_starts_once(self):
        service, started, _ = self.service()
        initializing, release = asyncio.Event(), asyncio.Event()
        async def initialize():
            initializing.set()
            await release.wait()
        service.initialize.side_effect = initialize
        with patch.object(runtime.cfg, "JJC_KUNGFU_REFRESH_ENABLED", 1, create=True):
            first = asyncio.create_task(runtime.start_kungfu_refresh(service))
            await initializing.wait()
            second = asyncio.create_task(runtime.start_kungfu_refresh(service))
            release.set()
            await asyncio.gather(first, second)
            await asyncio.wait_for(started.wait(), 1)
        service.initialize.assert_awaited_once()
        self.assertEqual(service.run_once.await_count, 1)

    async def test_disabled_does_not_initialize_or_import_singleton(self):
        service, _, _ = self.service()
        with patch.object(runtime.cfg, "JJC_KUNGFU_REFRESH_ENABLED", 0, create=True):
            await runtime.start_kungfu_refresh(service)
        service.initialize.assert_not_called()
        self.assertIsNone(runtime._task)

    async def test_initialization_failure_only_disables_optional_worker(self):
        service, _, _ = self.service()
        service.initialize.side_effect = ValueError("invalid isolated settings")
        with patch.object(runtime.cfg, "JJC_KUNGFU_REFRESH_ENABLED", 1, create=True), patch.object(runtime.logger, "error") as log:
            await runtime.start_kungfu_refresh(service)
        self.assertIsNone(runtime._task)
        service.run_once.assert_not_called()
        log.assert_called_once()

    async def test_empty_queue_and_unexpected_failure_sleep_instead_of_busy_loop(self):
        for outcome in (False, RuntimeError("isolated database failure")):
            with self.subTest(outcome=outcome):
                slept = asyncio.Event()
                async def idle(seconds):
                    self.assertEqual(seconds, 2)
                    slept.set()
                    await asyncio.Event().wait()
                service = SimpleNamespace(initialize=AsyncMock(), run_once=AsyncMock(side_effect=[outcome]))
                with patch.object(runtime.cfg, "JJC_KUNGFU_REFRESH_ENABLED", 1, create=True), \
                        patch.object(runtime.asyncio, "sleep", side_effect=idle), patch.object(runtime.logger, "error"):
                    await runtime.start_kungfu_refresh(service)
                    await asyncio.wait_for(slept.wait(), 1)
                    await runtime.stop_kungfu_refresh()
                self.assertEqual(service.run_once.await_count, 1)

    async def test_queue_integrity_error_stops_consumer_without_retry_or_automatic_catchup(self):
        service = SimpleNamespace(initialize=AsyncMock(),
            run_once=AsyncMock(side_effect=QueueIntegrityError("generation regressed")))
        with patch.object(runtime.cfg, "JJC_KUNGFU_REFRESH_ENABLED", 1, create=True), \
                patch.object(runtime.asyncio, "sleep", new=AsyncMock(
                    side_effect=AssertionError("fatal corruption must not enter retry loop"))) as sleep, \
                patch.object(runtime.logger, "error") as log:
            await runtime.start_kungfu_refresh(service)
            task = runtime._task
            with self.assertRaises(QueueIntegrityError):
                await task
            self.assertTrue(task.done())
            service.run_once.assert_awaited_once()
            sleep.assert_not_awaited()
            self.assertTrue(any("QueueIntegrityError" in str(call) for call in log.call_args_list))
