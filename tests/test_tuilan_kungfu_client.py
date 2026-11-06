"""Isolated async adapter contracts; no requests reach the upstream service."""
import asyncio
import json
import httpx
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.infra.tuilan_kungfu_client import KungfuQueryError, TuilanKungfuClient
from src.utils.tuilan_request import tuilan_request


IDENTITY = {"game_role_id": "42", "zone": "电信区", "server": "测试服", "name": "测试角色"}
SCOPE = {"season_id": "测试赛季", "season_start": 100, "pvp_type": 3, "algorithm_version": 1}


def indicator(**info):
    role = dict(role_id="42", global_role_id="SK01-example", server="测试服", zone="电信区")
    role.update(info)
    return {"code": 0, "data": {"role_info": role, "indicator": [
        {"type": "3c", "metrics": [{"pvp_type": 3, "kungfu": "bingxin", "win_count": 10,
                                    "items": [{"name": "sample"}]}]}]}}


class TuilanKungfuClientTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, responses, **kwargs):
        http = SimpleNamespace(arequest_json=AsyncMock(side_effect=responses))
        client = TuilanKungfuClient(http_client=http, request_interval=0, **kwargs)
        return client, http

    async def test_two_basic_requests_only_and_raw_result_for_shared_classifier(self):
        matches = [{"won": True, "kungfu": "bingxin"}]
        client, http = self.adapter([indicator(), {"code": 0, "data": matches}])
        result = await client.query(IDENTITY, SCOPE)
        self.assertEqual(result["matches"], matches)
        self.assertEqual(result["indicator_data"], indicator()["data"])
        self.assertLessEqual(result["requested_at"], result["verified_at"])
        calls = http.arequest_json.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].args[1].endswith("/role/indicator"))
        self.assertTrue(calls[1].args[1].endswith("/3c/mine/match/history"))
        self.assertEqual(json.loads(calls[1].kwargs["content"])["size"], 40)
        self.assertEqual(json.loads(calls[1].kwargs["content"])["global_role_id"], "SK01-example")

    async def test_legacy_and_async_build_identical_signed_utf8_request(self):
        client, http = self.adapter([indicator(global_role_id=None)])
        with patch("src.utils.tuilan_request.datetime.datetime") as clock, \
                patch("src.infra.http_client.HttpClient.request_json", return_value={"code": 0}) as legacy:
            clock.now.return_value.strftime.return_value = "20261106143000000"
            tuilan_request("https://local.test/indicator", {"role_id": "42", "zone": "电信区", "server": "测试服"})
            await client.query(IDENTITY, SCOPE)
        old, new = legacy.call_args.kwargs, http.arequest_json.call_args.kwargs
        self.assertEqual(old["headers"], new["headers"])
        self.assertEqual(old["content"], new["content"])
        self.assertEqual(json.loads(new["content"])["server"], "测试服")

    async def test_empty_history_and_general_history_failure_keep_indicator_fallback(self):
        for response in ({"code": 0, "data": []}, {"error": "request_failed"},
                         {"status_code": 500, "error": "http_status_500"}, {"code": -2, "msg": "temporary"}):
            with self.subTest(response=response):
                client, http = self.adapter([indicator(), response])
                result = await client.query(IDENTITY, SCOPE)
                self.assertEqual(result["matches"], [])
                self.assertTrue(result["indicator_data"])
                self.assertEqual(http.arequest_json.await_count, 2)
                if response.get("error") or response.get("code") != 0:
                    self.assertTrue(result["history_error_code"])

    async def test_indicator_failure_is_not_successful_empty_data(self):
        for response in ({"error": "request_failed"}, {"code": 0, "data": {}}, {"code": 5}):
            client, http = self.adapter([response])
            with self.assertRaises(KungfuQueryError):
                await client.query(IDENTITY, SCOPE)
            self.assertEqual(http.arequest_json.await_count, 1)

    async def test_missing_sk01_does_not_guess_history_identifier(self):
        client, http = self.adapter([indicator(global_role_id="123456")])
        result = await client.query(IDENTITY, SCOPE)
        self.assertEqual(result["matches"], [])
        self.assertEqual(http.arequest_json.await_count, 1)

    async def test_explicit_identity_mismatch_rejects_before_history(self):
        for info in ({"role_id": "other"}, {"server": "其他服"}, {"zone": "其他区"}):
            client, http = self.adapter([indicator(**info)])
            with self.assertRaises(KungfuQueryError) as error:
                await client.query(IDENTITY, SCOPE)
            self.assertEqual(error.exception.code, "identity_mismatch")
            self.assertEqual(http.arequest_json.await_count, 1)
        client, _ = self.adapter([indicator()])
        with self.assertRaises(KungfuQueryError):
            await client.query(dict(IDENTITY, global_role_id="SK01-other"), SCOPE)

    async def test_missing_optional_old_response_fields_does_not_change_legacy_contract(self):
        client, _ = self.adapter([{"code": 0, "data": {"role_info": {"role_id": "42"}, "indicator": []}}])
        self.assertEqual((await client.query(IDENTITY, SCOPE))["matches"], [])

    async def test_explicit_scope_conflict_is_rejected_but_missing_season_is_allowed(self):
        response = indicator()
        response["data"]["season_id"] = "different-season"
        client, http = self.adapter([response])
        with self.assertRaises(KungfuQueryError) as error:
            await client.query(IDENTITY, SCOPE)
        self.assertEqual(error.exception.code, "scope_mismatch")
        self.assertEqual(http.arequest_json.await_count, 1)

    async def test_auth_and_rate_limit_never_fall_back_on_history(self):
        responses = [{"status_code": 401}, {"status_code": 403},
                     {"code": -1, "msg": "请重新登录"},
                     {"status_code": 429, "retry_after": "12"},
                     {"status_code": 429, "retry_after": "999999"}]
        for response in responses:
            with self.subTest(response=response):
                client, http = self.adapter([indicator(), response])
                with self.assertRaises(KungfuQueryError) as error:
                    await client.query(IDENTITY, SCOPE)
                self.assertEqual(http.arequest_json.await_count, 2)
                if response.get("status_code") == 429:
                    self.assertEqual(error.exception.code, "rate_limited")
                    self.assertLessEqual(error.exception.retry_after, 3600)
                else:
                    self.assertTrue(error.exception.auth)
                    self.assertGreaterEqual(error.exception.retry_after, 300)

    async def test_default_transport_disables_internal_retries(self):
        self.assertEqual(TuilanKungfuClient().http_client.retries, 0)

    async def test_request_deadline_cancels_await_and_prevents_next_endpoint(self):
        cancelled = asyncio.Event()
        async def hangs(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        http = SimpleNamespace(arequest_json=AsyncMock(side_effect=hangs))
        client = TuilanKungfuClient(http_client=http, request_interval=0,
                                   request_timeout=0.02, attempt_timeout=0.08)
        started = time.monotonic()
        with self.assertRaises(KungfuQueryError) as error:
            await client.query(IDENTITY, SCOPE)
        self.assertEqual(error.exception.code, "request_timeout")
        self.assertLess(time.monotonic() - started, 0.3)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(http.arequest_json.await_count, 1)

    async def test_attempt_deadline_includes_interval_wait(self):
        client, http = self.adapter([indicator()], attempt_timeout=0.02)
        client.request_interval = 2
        with self.assertRaises(KungfuQueryError) as error:
            await client.query(IDENTITY, SCOPE)
        self.assertEqual(error.exception.code, "attempt_timeout")
        self.assertEqual(http.arequest_json.await_count, 1)

    async def test_explicit_cancellation_propagates_without_followup_request(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def hangs(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        http = SimpleNamespace(arequest_json=AsyncMock(side_effect=hangs))
        client = TuilanKungfuClient(http_client=http, request_interval=0)
        task = asyncio.create_task(client.query(IDENTITY, SCOPE))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())
        self.assertEqual(http.arequest_json.await_count, 1)

    async def test_request_start_interval_uses_injected_monotonic_clock(self):
        value, starts, waits = [0.0], [], []
        async def sleep(seconds):
            waits.append(seconds)
            value[0] += seconds
        async def request(*args, **kwargs):
            starts.append(value[0])
            return indicator() if len(starts) == 1 else {"code": 0, "data": []}
        client = TuilanKungfuClient(http_client=SimpleNamespace(arequest_json=request),
                                   monotonic=lambda: value[0], sleep=sleep)
        await client.query(IDENTITY, SCOPE)
        self.assertEqual(starts, [0.0, 2.0])
        self.assertEqual(waits, [2.0])


class RealAsyncTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_total_deadline_cancels_slow_body_in_existing_http_client(self):
        closed = asyncio.Event()
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                try:
                    yield b"{"
                    await asyncio.Event().wait()
                finally:
                    closed.set()
        async def handle(request):
            return httpx.Response(200, stream=SlowBody())
        real_client = httpx.AsyncClient
        def isolated_client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)
        adapter = TuilanKungfuClient(request_interval=0, request_timeout=0.02, attempt_timeout=0.1)
        with patch("src.infra.http_client.httpx.AsyncClient", side_effect=isolated_client):
            with self.assertRaises(KungfuQueryError) as error:
                await adapter.query(IDENTITY, SCOPE)
        self.assertEqual(error.exception.code, "request_timeout")
        self.assertTrue(closed.is_set())

    async def test_existing_async_transport_preserves_rate_limit_retry_header(self):
        async def handle(request):
            return httpx.Response(429, headers={"Retry-After": "17"}, json={"code": 429})
        real_client = httpx.AsyncClient
        def isolated_client(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)
        adapter = TuilanKungfuClient(request_interval=0)
        with patch("src.infra.http_client.httpx.AsyncClient", side_effect=isolated_client):
            with self.assertRaises(KungfuQueryError) as error:
                await adapter.query(IDENTITY, SCOPE)
        self.assertEqual(error.exception.code, "rate_limited")
        self.assertEqual(error.exception.retry_after, 17)

    async def test_history_request_timeout_preserves_legacy_indicator_fallback(self):
        async def request(method, url, **kwargs):
            if url.endswith("/role/indicator"):
                return indicator()
            raise asyncio.TimeoutError
        adapter = TuilanKungfuClient(http_client=SimpleNamespace(arequest_json=request), request_interval=0)
        result = await adapter.query(IDENTITY, SCOPE)
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["history_error_code"], "request_timeout")
