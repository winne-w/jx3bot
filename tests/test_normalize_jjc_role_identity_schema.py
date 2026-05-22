import unittest
from datetime import datetime, timezone

from scripts.normalize_jjc_role_identity_schema import (
    build_normalize_update,
    build_query,
    normalize_profile_history,
)


class TestNormalizeJjcRoleIdentitySchema(unittest.TestCase):
    def test_build_query_filters_source_and_identity_key(self) -> None:
        self.assertEqual(
            build_query("match_replay_indicator_backfill", "global_id:1"),
            {"sources": "match_replay_indicator_backfill", "identity_key": "global_id:1"},
        )
        self.assertEqual(build_query("all", None), {})

    def test_normalizes_time_fields_and_history_empty_fields(self) -> None:
        doc = {
            "identity_key": "global_id:gid-a",
            "server": "梦江南",
            "name": "角色A",
            "updated_at": 1779210000.0,
            "first_seen_at": 1779209338,
            "last_seen_at": datetime(2026, 5, 22, tzinfo=timezone.utc),
            "role_info_updated_at": 1779210000.0,
            "profile_history": [
                {
                    "server": "梦江南",
                    "name": "角色A",
                    "person_id": None,
                    "zone": "",
                    "global_id": "gid-a",
                    "observed_at": 1779209338.0,
                }
            ],
        }

        update, reasons = build_normalize_update(doc)

        self.assertIsNotNone(update)
        assert update is not None
        self.assertIn("updated_at", update["$set"])
        self.assertIn("first_seen_at", update["$set"])
        self.assertIsInstance(update["$set"]["updated_at"], datetime)
        self.assertIsInstance(update["$set"]["first_seen_at"], datetime)
        self.assertNotIn("role_info_updated_at", update["$set"])
        self.assertEqual(update["$set"]["profile_history"][0]["global_id"], "gid-a")
        self.assertNotIn("person_id", update["$set"]["profile_history"][0])
        self.assertNotIn("zone", update["$set"]["profile_history"][0])
        self.assertIsInstance(update["$set"]["profile_history"][0]["observed_at"], datetime)
        self.assertEqual(reasons["profile_history"], "clean_empty_or_time_fields")

    def test_does_not_change_identity_profile_values(self) -> None:
        doc = {
            "identity_key": "global_id:gid-a",
            "server": "梦江南",
            "name": "角色A",
            "zone": "电信区",
            "role_id": "rid-a",
            "game_role_id": "rid-a",
            "global_id": "gid-a",
            "global_role_id": "SK01-a",
            "person_id": "person-a",
            "updated_at": 1779210000.0,
        }

        update, _ = build_normalize_update(doc)

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(set(update["$set"].keys()), {"updated_at"})

    def test_normalize_profile_history_ignores_non_dict_entries(self) -> None:
        history, changed = normalize_profile_history(["bad", {"person_id": "", "global_id": "gid-a"}])

        self.assertTrue(changed)
        self.assertEqual(history[0], "bad")
        self.assertEqual(history[1], {"global_id": "gid-a"})


if __name__ == "__main__":
    unittest.main()
