import json
import unittest
from unittest.mock import patch

from src.utils.tuilan_request import calculate_xsk, tuilan_request
import config


class TestTuilanDirectRequest(unittest.TestCase):
    def test_legacy_budget_settings_do_not_block_official_requests(self):
        with patch.object(config, "TUILAN_PROTECTION_ENABLED", True, create=True), \
                patch.object(config, "TUILAN_BUDGET_GROUP", "", create=True), \
                patch("src.infra.http_client.HttpClient.request_json", return_value={"code": 0}) as http:
            for _ in range(5):
                self.assertEqual({"code": 0}, tuilan_request("https://local.test/history", {"cursor": 0}))
        self.assertEqual(5, http.call_count)

    def test_direct_request_preserves_utf8_signature_ticket_and_timestamp(self):
        params = {"server": "龙争虎斗", "role_id": "123"}
        with patch.object(config, "TICKET", "test-ticket"), \
                patch("src.infra.http_client.HttpClient.request_json", return_value={"code": 0}) as http:
            tuilan_request("https://local.test/indicator", params)
        payload = http.call_args.kwargs
        data = json.loads(payload["content"].decode("utf-8"))
        self.assertEqual("龙争虎斗", data["server"])
        self.assertEqual(17, len(data["ts"]))
        self.assertEqual(calculate_xsk(data)[0], payload["headers"]["X-Sk"])
        self.assertEqual("test-ticket", payload["headers"]["token"])
        self.assertNotIn("ts", params)
