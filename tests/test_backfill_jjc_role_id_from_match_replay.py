import unittest
from argparse import Namespace
from datetime import datetime

from scripts.backfill_jjc_role_id_from_match_replay import (
    build_detail_player_map,
    build_insert_doc,
    build_update,
    merge_detail_hint,
    parse_replay_role_name,
    resolve_range,
)


class TestBackfillJjcRoleIdFromMatchReplay(unittest.TestCase):
    def test_detail_hint_adds_zone_and_person_id_to_replay_player(self) -> None:
        match_detail_doc = {
            "data": {
                "detail": {
                    "team1": {
                        "players_info": [
                            {
                                "server": "梦江南",
                                "role_name": "角色A",
                                "zone": "电信区",
                                "person_id": "person-a",
                            }
                        ]
                    },
                    "team2": {"players_info": []},
                }
            }
        }
        player = {
            "role_id": "rid-a",
            "global_id": "gid-a",
            **parse_replay_role_name("角色A·梦江南"),
        }

        merged = merge_detail_hint(player, build_detail_player_map(match_detail_doc))

        self.assertEqual(merged["zone"], "电信区")
        self.assertEqual(merged["person_id"], "person-a")

    def test_builds_role_identity_insert_with_global_id_key(self) -> None:
        player = {
            "role_id": "rid-a",
            "global_id": "gid-a",
            "zone": "电信区",
            **parse_replay_role_name("角色A·梦江南"),
        }

        doc = build_insert_doc(
            "role_identities",
            player,
            1779209338,
            "match_replay_indicator_backfill",
            1779210000.0,
            global_role_id="SK01-a",
            person_id="person-a",
        )

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc["identity_key"], "global_id:gid-a")
        self.assertEqual(doc["identity_level"], "global_id")
        self.assertEqual(doc["global_role_id"], "SK01-a")
        self.assertEqual(doc["person_id"], "person-a")
        self.assertEqual(doc["profile_history"][0]["global_id"], "gid-a")
        self.assertIsInstance(doc["profile_observed_at"], datetime)
        self.assertIsInstance(doc["first_seen_at"], datetime)
        self.assertIsInstance(doc["last_seen_at"], datetime)
        self.assertIsInstance(doc["updated_at"], datetime)
        self.assertIsInstance(doc["role_info_updated_at"], float)
        self.assertNotIn("created_at", doc)

    def test_role_identity_insert_history_omits_empty_person_id(self) -> None:
        player = {
            "role_id": "rid-a",
            "global_id": "gid-a",
            "zone": "电信区",
            **parse_replay_role_name("角色A·梦江南"),
        }

        doc = build_insert_doc(
            "role_identities",
            player,
            1779209338,
            "match_replay_indicator_backfill",
            1779210000.0,
            global_role_id="SK01-a",
            person_id=None,
        )

        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertNotIn("person_id", doc["profile_history"][0])

    def test_queue_insert_requires_sk01_global_role_id(self) -> None:
        player = {
            "role_id": "rid-a",
            "global_id": "gid-a",
            "zone": "电信区",
            **parse_replay_role_name("角色A·梦江南"),
        }

        doc = build_insert_doc(
            "jjc_sync_role_queue",
            player,
            1779209338,
            "match_replay_backfill",
            1779210000.0,
            global_role_id=None,
            person_id="person-a",
        )

        self.assertIsNone(doc)

    def test_role_identity_update_uses_datetime_and_profile_history_entry(self) -> None:
        player = {
            "role_id": "rid-a",
            "global_id": "gid-a",
            "zone": "电信区",
            **parse_replay_role_name("角色A·梦江南"),
        }
        existing = {
            "identity_key": "global_id:gid-a",
            "identity_level": "global_id",
            "server": "梦江南",
            "name": "角色A",
            "normalized_server": "梦江南",
            "normalized_name": "角色a",
            "global_id": "gid-a",
            "role_info_observed_match_time": 1779209000,
        }

        update, reason = build_update(
            "role_identities",
            existing,
            player,
            1779209338,
            "match_replay_indicator_backfill",
            1779210000.0,
            global_role_id="SK01-a",
            person_id=None,
        )

        self.assertEqual(reason, "update")
        self.assertIsNotNone(update)
        assert update is not None
        self.assertIsInstance(update["$set"]["updated_at"], datetime)
        self.assertIsInstance(update["$set"]["role_info_updated_at"], float)
        history_entry = update["$addToSet"]["profile_history"]
        self.assertEqual(history_entry["source"], "match_replay_indicator_backfill")
        self.assertNotIn("person_id", history_entry)

    def test_resolve_range_supports_one_based_closed_interval(self) -> None:
        args = Namespace(match_id=None, start=21, end=40, skip=0, limit=20)

        self.assertEqual(resolve_range(args), (20, 20))

    def test_resolve_range_rejects_match_id_with_interval(self) -> None:
        args = Namespace(match_id=123, start=1, end=20, skip=0, limit=20)

        with self.assertRaises(SystemExit):
            resolve_range(args)


if __name__ == "__main__":
    unittest.main()
