import asyncio
import logging
import unittest
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import httpx

from src.infra import http_client as http_client_mod
from src.infra.http_client import HttpClient, close_shared_async_clients
from src.infra.managed_task import LoopLocal, ManagedBackgroundTask, supervise_forever
from src.infra.tuilan_errors import TuilanAuthError, is_tuilan_auth_error


class TestLoopLocal(unittest.TestCase):
    def test_caches_per_running_loop_and_isolates_across_loops(self) -> None:
        local: LoopLocal[asyncio.Lock] = LoopLocal(asyncio.Lock)
        created_locks: List[asyncio.Lock] = []

        async def grab_twice() -> None:
            first = local.get()
            second = local.get()
            self.assertIs(first, second)
            created_locks.append(first)

        asyncio.run(grab_twice())
        asyncio.run(grab_twice())

        self.assertEqual(len(created_locks), 2)
        self.assertIsNot(created_locks[0], created_locks[1])

    def test_on_loop_change_and_clear(self) -> None:
        local: LoopLocal[object] = LoopLocal(object)
        changes: List[int] = []

        async def exercise() -> None:
            a = local.get(on_loop_change=lambda: changes.append(1))
            b = local.get(on_loop_change=lambda: changes.append(2))
            self.assertIs(a, b)
            self.assertEqual(changes, [1])
            local.clear()
            c = local.get(on_loop_change=lambda: changes.append(3))
            self.assertIsNot(a, c)
            self.assertEqual(changes, [1, 3])

        asyncio.run(exercise())


class TestSuperviseForever(unittest.IsolatedAsyncioTestCase):
    async def test_exponential_backoff_on_errors_and_error_summary(self) -> None:
        sleeps: List[float] = []
        calls = 0

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) >= 4:
                raise asyncio.CancelledError

        async def worker() -> Dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom-1")
            if calls == 2:
                return {"error": True, "message": "summary-fail"}
            if calls == 3:
                return {"stopped_reason": "auto_paused"}
            raise RuntimeError("boom-2")

        log = logging.getLogger("test.supervise.backoff")
        with patch("src.infra.managed_task.asyncio.sleep", side_effect=fake_sleep), \
                patch.object(log, "exception") as exc_log, \
                patch.object(log, "warning") as warn_log:
            with self.assertRaises(asyncio.CancelledError):
                await supervise_forever(
                    worker,
                    name="test-worker",
                    logger_obj=log,
                    initial_backoff=1.0,
                    max_backoff=3.0,
                    healthy_reset_seconds=60.0,
                    auto_paused_sleep=7.0,
                )

        # call1 exc -> sleep 1.0 (next delay 2.0)
        # call2 error summary -> sleep 2.0 (next delay min(3.0, 4.0) = 3.0)
        # call3 auto_paused -> sleep 7.0 (delay remains 3.0)
        # call4 exc -> sleep 3.0 -> CancelledError
        self.assertEqual(sleeps, [1.0, 2.0, 7.0, 3.0])
        self.assertEqual(exc_log.call_count, 2)
        self.assertEqual(warn_log.call_count, 1)

    async def test_healthy_run_resets_backoff(self) -> None:
        sleeps: List[float] = []
        calls = 0
        clock_values = iter([0.0, 1.0, 10.0, 100.0])

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) >= 2:
                raise asyncio.CancelledError

        async def worker() -> Dict[str, Any]:
            nonlocal calls
            calls += 1
            raise RuntimeError(f"err-{calls}")

        log = logging.getLogger("test.supervise.reset")
        with patch("src.infra.managed_task.asyncio.sleep", side_effect=fake_sleep), \
                patch("src.infra.managed_task.time.monotonic", side_effect=lambda: next(clock_values)), \
                patch.object(log, "exception"):
            with self.assertRaises(asyncio.CancelledError):
                await supervise_forever(
                    worker,
                    name="reset-worker",
                    logger_obj=log,
                    initial_backoff=1.0,
                    max_backoff=60.0,
                    healthy_reset_seconds=60.0,
                )

        self.assertEqual(sleeps, [1.0, 1.0])

    async def test_cancelled_error_propagates_immediately(self) -> None:
        async def cancelled_worker() -> None:
            raise asyncio.CancelledError

        sleep_mock = AsyncMock()
        log = logging.getLogger("test.supervise.cancel")
        with patch("src.infra.managed_task.asyncio.sleep", new=sleep_mock):
            with self.assertRaises(asyncio.CancelledError):
                await supervise_forever(
                    cancelled_worker,
                    name="cancel-worker",
                    logger_obj=log,
                    initial_backoff=0.01,
                )
        sleep_mock.assert_not_awaited()

    async def test_managed_background_task_lifecycle(self) -> None:
        started = asyncio.Event()

        async def run_once() -> Dict[str, Any]:
            started.set()
            await asyncio.Event().wait()
            return {"error": False}

        log = logging.getLogger("test.managed.task")
        task = ManagedBackgroundTask(
            run_once,
            name="demo-task",
            logger_obj=log,
            initial_backoff=0.01,
        )
        self.assertFalse(task.is_running())
        self.assertTrue(await task.start())
        await asyncio.wait_for(started.wait(), timeout=1.0)
        self.assertTrue(task.is_running())
        self.assertFalse(await task.start())
        self.assertEqual(task.snapshot(), {"name": "demo-task", "running": True, "started_count": 1})
        await task.stop()
        self.assertFalse(task.is_running())


class TestTuilanAuthError(unittest.TestCase):
    def test_error_attributes_and_predicate(self) -> None:
        err = TuilanAuthError("token expired", code="401")
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(str(err), "token expired")
        self.assertEqual(err.code, "401")
        self.assertTrue(is_tuilan_auth_error(err))

        default_err = TuilanAuthError()
        self.assertIsNone(default_err.code)
        self.assertTrue(is_tuilan_auth_error(default_err))

        self.assertFalse(is_tuilan_auth_error(RuntimeError("generic")))
        self.assertFalse(is_tuilan_auth_error(ValueError("bad")))


class TestHttpClientSharedPool(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await close_shared_async_clients()

    async def test_reuses_shared_client_per_verify_and_closes_cleanly(self) -> None:
        seen_clients: List[httpx.AsyncClient] = []
        seen_headers: List[Dict[str, str]] = []
        seen_timeouts: List[Any] = []

        async def fake_request(self_client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> httpx.Response:
            seen_clients.append(self_client)
            seen_headers.append(dict(kwargs.get("headers") or {}))
            seen_timeouts.append(kwargs.get("timeout"))
            return httpx.Response(200, json={"ok": True, "url": url})

        http = HttpClient(timeout=12.0, retries=0, default_headers={"X-Base": "1"})
        with patch.object(httpx.AsyncClient, "request", new=fake_request):
            r1 = await http.arequest_json("GET", "https://example.test/a", headers={"X-Req": "A"})
            r2 = await http.arequest_json("GET", "https://example.test/b", headers={"X-Req": "B"}, timeout=5.0)
            r3 = await http.arequest_json("GET", "https://example.test/c", verify=False)

        self.assertEqual(r1["ok"], True)
        self.assertEqual(r2["ok"], True)
        self.assertEqual(r3["ok"], True)

        self.assertIs(seen_clients[0], seen_clients[1])
        self.assertIsNot(seen_clients[0], seen_clients[2])
        self.assertIs(http_client_mod._SHARED_ASYNC_CLIENTS[True], seen_clients[0])
        self.assertIs(http_client_mod._SHARED_ASYNC_CLIENTS[False], seen_clients[2])
        self.assertEqual(seen_headers[0], {"X-Base": "1", "X-Req": "A"})
        self.assertEqual(seen_headers[1], {"X-Base": "1", "X-Req": "B"})
        self.assertEqual(seen_timeouts[0], 12.0)
        self.assertEqual(seen_timeouts[1], 5.0)

        client_true = seen_clients[0]
        client_false = seen_clients[2]
        await close_shared_async_clients()
        self.assertEqual(http_client_mod._SHARED_ASYNC_CLIENTS, {})
        self.assertTrue(client_true.is_closed)
        self.assertTrue(client_false.is_closed)

    async def test_mocked_async_client_uses_context_manager_without_touching_pool(self) -> None:
        async def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"mocked": True})

        real_cls = http_client_mod._REAL_ASYNC_CLIENT

        def stub_client(**kwargs: Any) -> httpx.AsyncClient:
            return real_cls(transport=httpx.MockTransport(handle), **kwargs)

        http = HttpClient(retries=0)
        with patch("src.infra.http_client.httpx.AsyncClient", side_effect=stub_client) as mock_cls:
            res = await http.arequest_json("GET", "https://example.test/mocked")

        self.assertEqual(res, {"mocked": True})
        self.assertEqual(mock_cls.call_count, 1)
        self.assertEqual(http_client_mod._SHARED_ASYNC_CLIENTS, {})


class TestHttpClientCrossLoopPool(unittest.TestCase):
    def test_shared_client_recreates_across_event_loops(self) -> None:
        clients_by_run: List[httpx.AsyncClient] = []

        async def fake_request(self_client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> httpx.Response:
            clients_by_run.append(self_client)
            return httpx.Response(200, json={"ok": True})

        async def run_once() -> None:
            http = HttpClient(retries=0)
            with patch.object(httpx.AsyncClient, "request", new=fake_request):
                await http.arequest_json("GET", "https://example.test/loop")

        try:
            asyncio.run(run_once())
            asyncio.run(run_once())
            self.assertEqual(len(clients_by_run), 2)
            self.assertIsNot(clients_by_run[0], clients_by_run[1])
        finally:
            asyncio.run(close_shared_async_clients())


if __name__ == "__main__":
    unittest.main()
