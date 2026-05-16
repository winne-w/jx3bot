import asyncio
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.audit_jjc_person_history_identity import (
    _fetch_payload,
    build_degraded_identity_key,
    build_repair_update,
    classify_identity_doc,
    ensure_apply_allowed,
)


class TestAuditJjcPersonHistoryIdentity(unittest.TestCase):
    def test_classifies_confirmed_valid_by_role_fields(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
                "zone": "zone-a",
                "game_role_id": "rid-a",
            },
            {
                "data": [
                    {
                        "person_id": "pid-a",
                        "global_role_id": "gid-a",
                        "server": "梦江南",
                        "role_name": "角色A",
                        "zone": "zone-a",
                        "role_id": "rid-a",
                    }
                ]
            },
            "role_identities",
        )

        self.assertEqual(result["category"], "confirmed_valid")
        self.assertEqual(result["reason"], "role_fields_match")

    def test_classifies_confirmed_dirty_when_same_global_conflicts(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
                "zone": "zone-a",
                "game_role_id": "rid-a",
            },
            {
                "data": [
                    {
                        "person_id": "pid-a",
                        "global_role_id": "gid-a",
                        "server": "梦江南",
                        "role_name": "角色B",
                        "zone": "zone-b",
                        "role_id": "rid-b",
                    }
                ]
            },
            "role_identities",
        )

        self.assertEqual(result["category"], "confirmed_dirty")
        self.assertEqual(result["repair_identity_key"], "game:zone-a:rid-a")

    def test_classifies_suspected_dirty_when_global_missing_but_same_person_exists(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
            },
            {
                "data": [
                    {
                        "person_id": "pid-a",
                        "global_role_id": "gid-other",
                        "server": "梦江南",
                        "role_name": "角色B",
                    }
                ]
            },
            "role_identities",
        )

        self.assertEqual(result["category"], "suspected_dirty")

    def test_classifies_conflict_when_repair_key_already_exists(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
                "zone": "zone-a",
                "game_role_id": "rid-a",
            },
            {
                "data": [
                    {
                        "person_id": "pid-a",
                        "global_role_id": "gid-a",
                        "server": "梦江南",
                        "role_name": "角色B",
                        "zone": "zone-b",
                        "role_id": "rid-b",
                    }
                ]
            },
            "role_identities",
            target_key_exists=True,
        )

        self.assertEqual(result["category"], "conflict_needs_manual_merge")

    def test_builds_role_identity_repair_update(self) -> None:
        now = datetime(2026, 5, 15, tzinfo=timezone.utc)
        update = build_repair_update(
            {
                "identity_key": "global:gid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
                "zone": "zone-a",
                "game_role_id": "rid-a",
            },
            "role_identities",
            now=now,
        )

        self.assertEqual(update["$set"]["identity_key"], "game:zone-a:rid-a")
        self.assertEqual(update["$set"]["identity_level"], "game_role")
        self.assertEqual(update["$set"]["identity_source"], "person_history_mismatch_cleaned")
        self.assertEqual(update["$unset"], {"global_role_id": ""})
        self.assertEqual(
            update["$set"]["person_history_audit"]["original_global_role_id"],
            "gid-a",
        )

    def test_builds_sync_queue_repair_update_and_resets_waterline(self) -> None:
        update = build_repair_update(
            {
                "identity_key": "global:gid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
                "normalized_server": "梦江南",
                "normalized_name": "角色A",
            },
            "jjc_sync_role_queue",
        )

        self.assertEqual(update["$set"]["identity_key"], "name:梦江南:角色A")
        self.assertEqual(update["$set"]["status"], "pending")
        self.assertIsNone(update["$set"]["full_synced_until_time"])
        self.assertIsNone(update["$set"]["oldest_synced_match_time"])
        self.assertIsNone(update["$set"]["latest_seen_match_time"])
        self.assertEqual(update["$unset"], {"global_role_id": ""})

    def test_apply_requires_yes(self) -> None:
        with self.assertRaises(ValueError):
            ensure_apply_allowed(apply=True, yes=False)
        ensure_apply_allowed(apply=False, yes=False)
        ensure_apply_allowed(apply=True, yes=True)

    def test_dry_run_namespace_defaults_to_no_write(self) -> None:
        args = Namespace(apply=False, yes=False)

        ensure_apply_allowed(args.apply, args.yes)
        self.assertFalse(args.apply)

    def test_classifies_api_failed_when_api_error_flag(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
            },
            {},
            "role_identities",
            api_error=True,
        )

        self.assertEqual(result["category"], "api_failed")

    def test_classifies_api_failed_when_payload_has_error_key(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
            },
            {"error": "timeout"},
            "role_identities",
        )

        self.assertEqual(result["category"], "api_failed")
        self.assertIn("timeout", result["reason"])

    def test_classifies_api_failed_when_payload_is_not_dict(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
            },
            "not_a_dict",
            "role_identities",
        )

        self.assertEqual(result["category"], "api_failed")

    def test_classifies_unknown_when_insufficient_evidence(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
                "server": "梦江南",
                "name": "角色A",
            },
            {"data": []},
            "role_identities",
        )

        self.assertEqual(result["category"], "unknown")
        self.assertIn("insufficient", result["reason"])

    def test_classifies_unknown_when_no_data_key(self) -> None:
        result = classify_identity_doc(
            {
                "identity_key": "global:gid-a",
                "person_id": "pid-a",
                "global_role_id": "gid-a",
            },
            {"other": "stuff"},
            "role_identities",
        )

        self.assertEqual(result["category"], "unknown")

    def test_degraded_key_fallback_strips_server_suffix_when_normalized_name_absent(self) -> None:
        key, level = build_degraded_identity_key({
            "server": "梦江南",
            "role_name": "角色A·梦江南",
        })

        self.assertEqual(key, "name:梦江南:角色a")
        self.assertEqual(level, "name")

    def test_degraded_key_prefers_game_role_over_name(self) -> None:
        key, level = build_degraded_identity_key({
            "server": "梦江南",
            "name": "角色A",
            "zone": "zone-a",
            "role_id": "rid-a",
        })

        self.assertEqual(key, "game:zone-a:rid-a")
        self.assertEqual(level, "game_role")


class FakePagedPersonHistoryClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_person_match_history(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return self.pages[index] if index < len(self.pages) else {"data": []}


class AsyncSleepCounter:
    def __init__(self) -> None:
        self.count = 0

    async def __call__(self) -> None:
        self.count += 1


class TestAuditPersonHistoryPagination(unittest.IsolatedAsyncioTestCase):
    async def _call_sync(self, func, *args, **kwargs):
        return func(*args, **kwargs)

    async def test_fetch_payload_stops_when_expected_role_is_found(self) -> None:
        client = FakePagedPersonHistoryClient([
            {
                "data": [{
                    "person_id": "pid-a",
                    "global_role_id": "gid-other",
                    "server": "梦江南",
                    "role_name": "其他角色",
                }]
            },
            {
                "data": [{
                    "person_id": "pid-a",
                    "global_role_id": "gid-target",
                    "server": "梦江南",
                    "role_name": "角色A",
                }]
            },
            {"data": []},
        ])
        expected = {
            "person_id": "pid-a",
            "global_role_id": "gid-old",
            "zone": "",
            "role_id": "",
            "server": "梦江南",
            "role_name": "角色A",
        }
        sleep = AsyncSleepCounter()

        with patch(
            "scripts.audit_jjc_person_history_identity.asyncio.to_thread",
            side_effect=self._call_sync,
        ):
            payload = await asyncio.wait_for(
                _fetch_payload(client, "pid-a", expected=expected, page_size=20, sleep_func=sleep),
                timeout=1,
            )

        self.assertEqual(len(payload["data"]), 2)
        self.assertEqual(
            [call["cursor"] for call in client.calls],
            [0, 20],
        )
        self.assertEqual(sleep.count, 1)

    async def test_fetch_payload_stops_on_error(self) -> None:
        client = FakePagedPersonHistoryClient([
            {"data": [{"id": 1}]},
            {"error": "http_status_503"},
        ])
        sleep = AsyncSleepCounter()

        with patch(
            "scripts.audit_jjc_person_history_identity.asyncio.to_thread",
            side_effect=self._call_sync,
        ):
            payload = await asyncio.wait_for(
                _fetch_payload(client, "pid-a", page_size=20, sleep_func=sleep),
                timeout=1,
            )

        self.assertEqual(payload, {"error": "http_status_503"})
        self.assertEqual(
            [call["cursor"] for call in client.calls],
            [0, 20],
        )
        self.assertEqual(sleep.count, 1)

    async def test_fetch_payload_fetches_until_empty_when_expected_role_not_found(self) -> None:
        client = FakePagedPersonHistoryClient([
            {"data": [{"person_id": "pid-a", "server": "梦江南", "role_name": "其他角色"}]},
            {"data": [{"person_id": "pid-a", "server": "梦江南", "role_name": "另一个角色"}]},
            {"data": []},
        ])
        expected = {
            "person_id": "pid-a",
            "global_role_id": "gid-old",
            "zone": "",
            "role_id": "",
            "server": "梦江南",
            "role_name": "角色A",
        }
        sleep = AsyncSleepCounter()

        with patch(
            "scripts.audit_jjc_person_history_identity.asyncio.to_thread",
            side_effect=self._call_sync,
        ):
            payload = await asyncio.wait_for(
                _fetch_payload(client, "pid-a", expected=expected, page_size=20, sleep_func=sleep),
                timeout=1,
            )

        self.assertEqual(len(payload["data"]), 2)
        self.assertEqual(
            [call["cursor"] for call in client.calls],
            [0, 20, 40],
        )
        self.assertEqual(sleep.count, 2)


if __name__ == "__main__":
    unittest.main()
