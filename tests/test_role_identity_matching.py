import unittest
from copy import deepcopy
from datetime import datetime, timezone

from src.services.jx3 import role_identity_matching as matching

from src.services.jx3.role_identity_matching import (
    build_identity_key,
    build_profile_history_entry,
    classify_identity_conflicts,
    classify_profile_change,
    extract_replay_players,
    merge_profile_history,
    parse_indicator_identity,
    split_replay_role_name,
)


class TestRoleIdentityMatching(unittest.TestCase):
    def test_split_replay_role_name(self) -> None:
        self.assertEqual(split_replay_role_name("角色A·梦江南"), ("梦江南", "角色A"))
        self.assertEqual(split_replay_role_name("角色A", "梦江南"), ("梦江南", "角色A"))

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


class TestVerifiedQueryIdRules(unittest.TestCase):
    def setUp(self):
        self.existing = {
            "identity_key": "global_id:10001", "global_id": "10001",
            "global_role_id": "SK01-test", "server": "new-server",
            "normalized_server": "new-server", "name": "test-role",
            "normalized_name": "test-role", "zone": "zone-a",
            "role_id": "31300496", "game_role_id": "31300496",
            "role_info_observed_match_time": 200,
        }
        self.indicator = {"code": 0, "data": {
            "role_info": {"role_id": "34945120", "server": "new-server",
                          "zone": "zone-a", "name": "test-role",
                          "global_role_id": "SK01-test"},
            "indicator": [{"type": "3c", "total_count": 12, "score": 2200}],
        }}
        self.replay = {"code": 0, "data": {"players": [{
            "global_role_id": "10001", "role_id": "34945120",
            "role_name": "test-role\u00b7new-server", "zone": "zone-a",
        }]}}

    def valid(self, **changes):
        validator = getattr(matching, "validate_query_id_evidence", None)
        self.assertTrue(callable(validator), "strict original-response validator is required")
        arguments = dict(request_zone="zone-a", request_server="new-server",
                         request_role_id="34945120", indicator_data=self.indicator,
                         replay_data=self.replay)
        arguments.update(changes)
        return validator(self.existing, **arguments)

    def mark_verified(self):
        self.existing.update(
            global_role_id_refreshed_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
            global_role_id_refresh_source="indicator_replay_verified",
        )

    def test_three_transition_fixtures_reproduce_fill_only_dead_end(self):
        for old_id, current_id in [("31300496", "34945120"),
                                   ("44421059", "31755654"),
                                   ("34971082", "26691973")]:
            with self.subTest(old_id=old_id):
                old = dict(self.existing, server="old-server", role_id=old_id,
                           game_role_id=old_id, role_info_observed_match_time=100)
                delta = matching.build_guarded_profile_set_fields(
                    old, {"server": "new-server", "role_id": "", "game_role_id": ""},
                    observed_match_time=200)
                mixed = dict(old, **delta, role_info_observed_match_time=200)
                self.assertEqual(mixed["server"], "new-server")
                self.assertEqual(mixed["role_id"], old_id)
                for observed in (None, 200):
                    self.assertNotIn("role_id", matching.build_guarded_profile_set_fields(
                        mixed, {"role_id": current_id}, observed_match_time=observed))

    def test_strict_observation_blocks_entire_conflicting_combination_even_future_match(self):
        self.mark_verified()
        for observed in (None, 199, 200, 9999999999):
            with self.subTest(observed=observed):
                delta = matching.build_guarded_profile_set_fields(self.existing, {
                    "server": "old-server", "normalized_server": "old-server",
                    "name": "old-name", "normalized_name": "old-name",
                    "zone": "old-zone", "role_id": "old-id", "game_role_id": "old-id",
                }, observed_match_time=observed)
                self.assertEqual(delta, {}, "historical time is not strict identity proof")

    def test_strict_observation_does_not_allow_force_profile_bypass(self):
        self.mark_verified()
        delta = matching.build_guarded_profile_set_fields(
            self.existing, {"server": "old-server", "role_id": "bad-id"},
            observed_match_time=300, force_profile_update=True)
        self.assertEqual(delta, {})

    def test_ordinary_refresh_marker_retains_legacy_newer_match_rules(self):
        self.existing["global_role_id_refresh_source"] = "indicator_api"
        self.existing["global_role_id_refreshed_at"] = datetime.now(timezone.utc)
        delta = matching.build_guarded_profile_set_fields(
            self.existing, {"role_id": "new-id"}, observed_match_time=201)
        self.assertEqual(delta["role_id"], "new-id")

    def test_valid_original_indicator_and_exact_numeric_replay_are_accepted(self):
        self.assertTrue(self.valid())

    def test_indicator_response_and_request_must_match_target(self):
        for field, value in [("role_id", "wrong"), ("server", "wrong"),
                             ("zone", "wrong"), ("global_role_id", "SK01-other"),
                             ("name", "different-role")]:
            with self.subTest(field=field):
                payload = deepcopy(self.indicator)
                payload["data"]["role_info"][field] = value
                self.assertFalse(self.valid(indicator_data=payload))
        for field in ("request_zone", "request_server", "request_role_id"):
            self.assertFalse(self.valid(**{field: "wrong"}))

    def test_unsuccessful_empty_or_fallback_indicator_is_not_proof(self):
        invalid = [dict(self.indicator, code=429),
                   dict(self.indicator, code=False),
                   {"data": self.indicator["data"]},
                   {"code": 0, "data": {"role_info": {}}},
                   {"source": "indicator", "global_id": "10001", "total_matches": 12}]
        empty = deepcopy(self.indicator)
        empty["data"]["indicator"] = [{"type": "3c"}]
        invalid.append(empty)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertFalse(self.valid(indicator_data=payload))

    def test_numeric_mapping_cannot_be_self_certified_by_wrapper_or_same_name(self):
        cases = [{"code": 0, "global_id": "10001", "data": {"players": []}}]
        wrong_numeric = deepcopy(self.replay)
        wrong_numeric["data"]["players"][0]["global_role_id"] = "20002"
        cases.append(wrong_numeric)
        sk01_not_numeric = deepcopy(self.replay)
        sk01_not_numeric["data"]["players"][0]["global_role_id"] = "SK01-test"
        cases.append(sk01_not_numeric)
        conflicting = deepcopy(self.replay)
        conflicting["data"]["players"].append(dict(
            conflicting["data"]["players"][0], role_id="another-id"))
        cases.append(conflicting)
        duplicate_locator = deepcopy(self.replay)
        duplicate_locator["data"]["players"].append(dict(
            duplicate_locator["data"]["players"][0], global_role_id="20002"))
        cases.append(duplicate_locator)
        cases.append(dict(self.replay, code=1))
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertFalse(self.valid(replay_data=payload))

    def test_later_transfer_cannot_sneak_in_through_id_only_recovery(self):
        payload = deepcopy(self.indicator)
        payload["data"]["role_info"]["server"] = "third-server"
        self.mark_verified()
        self.assertFalse(self.valid(request_server="third-server", indicator_data=payload))
