import unittest
from datetime import datetime, timezone

from src.services.jx3.role_identity_matching import (
    build_identity_key,
    build_profile_history_entry,
    classify_identity_conflicts,
    classify_profile_change,
    extract_replay_players,
    merge_profile_history,
    normalize_match_detail_role_name,
    parse_indicator_identity,
    split_replay_role_name,
)


class TestRoleIdentityMatching(unittest.TestCase):
    def test_split_replay_role_name(self) -> None:
        self.assertEqual(split_replay_role_name("角色A·梦江南"), ("梦江南", "角色A"))
        self.assertEqual(split_replay_role_name("角色A", "梦江南"), ("梦江南", "角色A"))

    def test_normalize_match_detail_role_name_only_strips_verified_server_suffix(self) -> None:
        self.assertEqual(
            normalize_match_detail_role_name("角色A·梦江南", "梦江南", "梦江南"),
            "角色A",
        )
        self.assertEqual(
            normalize_match_detail_role_name("角色A·梦江南", "梦江南", "唯我独尊"),
            "角色A",
        )
        self.assertEqual(
            normalize_match_detail_role_name("张三·李四", "梦江南", "唯我独尊"),
            "张三·李四",
        )

    def test_build_identity_key_prefers_global_id(self) -> None:
        self.assertEqual(
            build_identity_key(
                global_id="99999",
                global_role_id="SK01-abc",
                zone="电信区",
                game_role_id="rid-a",
                server="梦江南",
                name="角色A",
            ),
            ("global_id:99999", "global_id"),
        )
        self.assertEqual(
            build_identity_key(global_role_id="SK01-abc", zone="z", game_role_id="rid"),
            ("global:SK01-abc", "global"),
        )

    def test_extract_replay_players_maps_numeric_global_role_id_to_global_id(self) -> None:
        players = extract_replay_players(
            {
                "data": {
                    "players": [
                        {
                            "role_id": "rid-a",
                            "global_role_id": "99999",
                            "role_name": "角色A·梦江南",
                            "kungfu_id": 10021,
                        }
                    ]
                }
            },
            server_zone_map={"梦江南": "电信区"},
        )

        self.assertEqual(players[0]["global_id"], "99999")
        self.assertEqual(players[0]["role_id"], "rid-a")
        self.assertEqual(players[0]["server"], "梦江南")
        self.assertEqual(players[0]["name"], "角色A")
        self.assertEqual(players[0]["zone"], "电信区")

    def test_parse_indicator_accepts_only_sk01_global_role_id(self) -> None:
        identity = parse_indicator_identity({
            "data": {
                "role_info": {
                    "global_role_id": "SK01-abc",
                    "role_id": "rid-a",
                    "zone": "电信区",
                    "server": "梦江南",
                    "name": "角色A",
                },
                "person_info": {"person_id": "person-a"},
            }
        })
        self.assertEqual(identity["global_role_id"], "SK01-abc")
        self.assertEqual(identity["person_id"], "person-a")

        identity = parse_indicator_identity({"data": {"role_info": {"global_role_id": "99999"}}})
        self.assertIsNone(identity["global_role_id"])

    def test_profile_history_merge_deduplicates_stable_identity(self) -> None:
        observed_at = datetime(2026, 5, 21, tzinfo=timezone.utc)
        entry = build_profile_history_entry(
            server="梦江南",
            name="角色A",
            zone="电信区",
            role_id="rid-a",
            global_role_id="SK01-abc",
            global_id="99999",
            source="match_replay",
            observed_at=observed_at,
        )
        duplicate = dict(entry)

        merged = merge_profile_history([entry], [duplicate])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["global_id"], "99999")

    def test_classify_identity_conflicts(self) -> None:
        conflicts = classify_identity_conflicts([
            {"global_id": "99999", "role_id": "rid-a", "zone": "电信区", "person_id": "p1"},
            {"global_id": "99999", "role_id": "rid-b", "zone": "电信区", "person_id": "p2"},
            {"global_role_id": "SK01-abc", "global_id": "99999"},
            {"global_role_id": "SK01-abc", "global_id": "88888"},
        ])
        conflict_types = {item["type"] for item in conflicts}

        self.assertIn("global_id_conflict", conflict_types)
        self.assertIn("global_role_id_global_id_conflict", conflict_types)
        self.assertIn("person_id_conflict", conflict_types)

    def test_classify_profile_change(self) -> None:
        changed = classify_profile_change(
            {"server": "旧服", "name": "旧名", "role_id": "rid-a"},
            {"server": "新服", "name": "旧名", "role_id": "rid-b"},
        )

        self.assertEqual(changed, ["server", "role_id"])


if __name__ == "__main__":
    unittest.main()
