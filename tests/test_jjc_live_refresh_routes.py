import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from src.services.jx3.jjc_public_refresh import source_key

from tests.test_jjc_ranking_stats_router import _load_router_module, _FakeInspectService


class TestLiveRefreshRoutes(unittest.IsolatedAsyncioTestCase):
    async def post(self, payload, *, allowed=True, storage_error=False):
        with patch.dict(sys.modules):
            router = _load_router_module()
            allow_source = AsyncMock(return_value=allowed)
            if storage_error:
                allow_source.side_effect = RuntimeError("isolated database failure")
            live = types.SimpleNamespace(
                enabled=lambda: True,
                repo=types.SimpleNamespace(allow_source=allow_source),
                submit=AsyncMock(return_value={"state": "queued"}),
            )
            sys.modules["src.services.jx3.singletons"].jjc_live_refresh_service = live
            request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
            with patch.multiple(sys.modules["config"], JJC_LIVE_SOURCE_SECRET="test-secret",
                                JJC_LIVE_TRUSTED_PROXIES="", create=True):
                return await router.post_ranking_stats_synced_role_refresh(request, payload)

    async def test_post_rejects_missing_non_string_and_empty_names(self):
        for payload in ({}, {"server": "s", "name": 1}, {"server": "s", "name": "  "}):
            with self.subTest(payload=payload):
                response = await self.post(payload)
                self.assertEqual(400, response.status_code)

    async def test_post_accepts_valid_role(self):
        response = await self.post({"server": "s", "name": "known"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("queued", json.loads(response.body)["data"]["state"])

    async def test_post_source_limit_returns_retry_after(self):
        response = await self.post({"server": "s", "name": "known"}, allowed=False)
        self.assertEqual(429, response.status_code)
        self.assertEqual("60", response.headers["retry-after"])
        self.assertEqual("rate_limited", json.loads(response.body)["data"]["state"])

    async def test_post_storage_failure_returns_safe_error_and_retry_after(self):
        response = await self.post({"server": "s", "name": "known"}, storage_error=True)
        self.assertEqual(503, response.status_code)
        self.assertEqual("60", response.headers["retry-after"])
        self.assertEqual("storage_unavailable", json.loads(response.body)["data"]["state"])
        self.assertNotIn("isolated database failure", response.body.decode())

    async def test_disabled_refresh_still_reads_saved_summary_without_submitting(self):
        with patch.dict(sys.modules):
            router = _load_router_module()
            inspect = _FakeInspectService()
            inspect.synced_matches_result = {"identity": {"identity_id": "known"}, "recent_matches": []}
            router.jjc_ranking_inspect_service = inspect
            live = types.SimpleNamespace(read=AsyncMock(return_value={
                "latest_matches": [{"match_id": 1}], "refresh": {"enabled": False, "state": "disabled"}}),
                submit=AsyncMock())
            sys.modules["src.services.jx3.singletons"].jjc_live_refresh_service = live
            with patch.object(sys.modules["config"], "JJC_LIVE_REFRESH_ENABLED", 0, create=True):
                result = await router.get_ranking_stats_synced_role_matches(server="server", name="known", page=1, page_size=20)
            self.assertEqual([{"match_id": 1}], result["data"]["latest_matches"])
            self.assertEqual("disabled", result["data"]["refresh"]["state"])
            live.submit.assert_not_called()


class TestTrustedRefreshSource(unittest.TestCase):
    def test_untrusted_forwarded_header_does_not_change_source(self):
        self.assertEqual(source_key("10.0.0.2", "1.1.1.1", "", "test"),
                         source_key("10.0.0.2", "9.9.9.9", "", "test"))

    def test_trusted_proxy_chain_stops_at_first_untrusted_hop(self):
        self.assertEqual(source_key("10.0.0.2", "9.9.9.9, 1.1.1.1", "10.0.0.0/8", "test"),
                         source_key("1.1.1.1", "", "", "test"))
