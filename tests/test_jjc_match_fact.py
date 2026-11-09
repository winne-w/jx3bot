from __future__ import annotations

import hashlib
import json
import math
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

from src.services.jx3.jjc_match_fact import (
    build_match_fact,
    build_source_hash,
    encode_combo_key,
    extract_match_time,
    normalize_game_score,
    normalize_positive_int,
)
from src.services.jx3 import jjc_match_fact


def make_player(kungfu_id: Any, **overrides: Any) -> Dict[str, Any]:
    player = {
        "role_name": "角色%s" % kungfu_id,
        "server": "梦江南",
        "kungfu_id": kungfu_id,
        "kungfu": "心法%s" % kungfu_id,
        "total_score": 1000,
        "score": 900,
        "global_id": None,
        "armors": [{"name": "不得进入事实"}],
        "talents": [{"name": "不得进入事实"}],
        "metrics": [{"name": "不得进入事实"}],
    }
    player.update(overrides)
    return player


def make_payload(**overrides: Any) -> Dict[str, Any]:
    detail = {
        "match_time": 1700000100,
        "basic_info": {
            "match_type": 3,
            "start_time": 1700000000,
            "map": "华山之巅",
            "duration": 180,
        },
        "team1": {
            "won": True,
            "players_info": [make_player(10001), make_player(10002), make_player(10003)],
        },
        "team2": {
            "won": False,
            "players_info": [make_player(10004), make_player(10005), make_player(10006)],
        },
        "replay": {"large": ["不得进入事实"]},
    }
    payload: Dict[str, Any] = {
        "cached_at": 1700000200,
        "data": {"match_id": 123, "detail": detail},
    }
    payload.update(overrides)
    return payload


def detail_of(payload: Dict[str, Any]) -> Dict[str, Any]:
    return payload["data"]["detail"]


class TestNormalizers(unittest.TestCase):
    def test_positive_int_accepts_only_positive_integral_values(self) -> None:
        self.assertEqual(normalize_positive_int(12), 12)
        self.assertEqual(normalize_positive_int(12.0), 12)
        self.assertEqual(normalize_positive_int("12"), 12)
        for value in (True, False, 0, -1, 1.5, float("nan"), float("inf"), "", " 12", "+12", "012", "12.0", "abc"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_positive_int(value))

    def test_game_score_accepts_zero_and_falls_back_for_all_invalid_forms(self) -> None:
        self.assertEqual(normalize_game_score(0), 0)
        self.assertEqual(normalize_game_score(1000000.0), 1000000)
        self.assertEqual(normalize_game_score("42"), 42)
        for value in (True, -1, 1000001, 1.5, float("nan"), -float("inf"), "", " 42", "+42", "042", "42.0"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_game_score(value))


class TestMatchTime(unittest.TestCase):
    def test_data_envelope_time_wins_over_older_nested_detail_time(self) -> None:
        payload = make_payload()
        payload["data"]["match_time"] = 1700000300
        detail_of(payload)["match_time"] = 1700000100
        self.assertEqual(extract_match_time(payload), 1700000300)

    def test_accepts_every_compatible_alias_at_each_priority_level(self) -> None:
        for key in ("match_time", "matchTime", "start_time", "startTime", "time"):
            with self.subTest(level="payload", key=key):
                payload = make_payload(**{key: "1700000300"})
                self.assertEqual(extract_match_time(payload), 1700000300)
            with self.subTest(level="data_envelope", key=key):
                payload = make_payload()
                payload["data"][key] = "1700000350"
                self.assertEqual(extract_match_time(payload), 1700000350)
            with self.subTest(level="detail", key=key):
                payload = make_payload()
                del detail_of(payload)["match_time"]
                detail_of(payload)[key] = "1700000400"
                self.assertEqual(extract_match_time(payload), 1700000400)
            with self.subTest(level="basic_info", key=key):
                payload = make_payload()
                del detail_of(payload)["match_time"]
                detail_of(payload)["basic_info"] = {key: "1700000500"}
                self.assertEqual(extract_match_time(payload), 1700000500)

    def test_extracts_actual_time_in_payload_detail_basic_info_priority(self) -> None:
        payload = make_payload(match_time="1700000300")
        self.assertEqual(extract_match_time(payload), 1700000300)

        del payload["match_time"]
        del detail_of(payload)["match_time"]
        detail_of(payload)["matchTime"] = "1700000400"
        self.assertEqual(extract_match_time(payload), 1700000400)

        del detail_of(payload)["matchTime"]
        del detail_of(payload)["basic_info"]["start_time"]
        detail_of(payload)["basic_info"]["startTime"] = "1700000500"
        self.assertEqual(extract_match_time(payload), 1700000500)

    def test_ignores_cached_at_and_current_time_fallbacks(self) -> None:
        payload = make_payload()
        detail = detail_of(payload)
        del detail["match_time"]
        detail["basic_info"] = {}
        self.assertIsNone(extract_match_time(payload))


class TestComboKeys(unittest.TestCase):
    def test_combination_encoding_is_order_independent_and_multiplicity_safe(self) -> None:
        self.assertEqual(encode_combo_key([10080, 10080]), "v1:2:10080,10080")
        self.assertEqual(encode_combo_key([3, 1, 2]), "v1:3:1,2,3")
        with self.assertRaises(ValueError):
            encode_combo_key([])
        with self.assertRaises(ValueError):
            encode_combo_key([1, 0])


class TestBuildMatchFact(unittest.TestCase):
    def test_builds_active_fact_for_valid_3v3_without_global_ids(self) -> None:
        fact = build_match_fact(123, make_payload(), 1)

        self.assertTrue(fact["active"])
        self.assertEqual(fact["match_id"], 123)
        self.assertEqual(fact["match_time"], 1700000100)
        self.assertEqual(fact["source_cached_at"], 1700000200)
        self.assertEqual(fact["schema_version"], 1)
        self.assertEqual(fact["team1"]["kungfu_ids"], [10001, 10002, 10003])
        self.assertEqual(fact["team1"]["score_sum"], 3000)
        self.assertEqual(fact["team1"]["score_count"], 3)
        self.assertTrue(fact["team1"]["score_complete"])
        self.assertEqual(fact["team1"]["score_avg"], 1000.0)
        self.assertEqual(fact["min_team_score_sum"], 3000)
        self.assertEqual(fact["max_team_score_sum"], 3000)
        self.assertIn("v1:2:10001,10002", fact["team1"]["combo_keys"])
        self.assertIn("v1:3:10001,10002,10003", fact["any_team_combo_keys"])
        self.assertNotIn("global_id", fact["team1"]["players"][0])
        serialized = json.dumps(fact, ensure_ascii=False, sort_keys=True)
        for forbidden in ("armors", "talents", "metrics", "replay", "不得进入事实"):
            self.assertNotIn(forbidden, serialized)

    def test_total_score_has_priority_but_invalid_total_score_falls_back_to_score_and_zero_is_valid(self) -> None:
        payload = make_payload()
        players = detail_of(payload)["team1"]["players_info"]
        players[0].update(total_score=0, score=999)
        players[1].update(total_score="bad", score="700")
        players[2].update(total_score=True, score=800)

        fact = build_match_fact(123, payload, 1)

        self.assertEqual([item["game_score"] for item in fact["team1"]["players"]], [0, 700, 800])
        self.assertEqual([item["score_source"] for item in fact["team1"]["players"]], ["total_score", "score", "score"])
        self.assertEqual(fact["team1"]["score_sum"], 1500)

    def test_invalid_scores_leave_an_active_but_incomplete_fact(self) -> None:
        payload = make_payload()
        player = detail_of(payload)["team1"]["players_info"][0]
        player.update(total_score=math.nan, score="1000001")

        fact = build_match_fact(123, payload, 1)

        self.assertTrue(fact["active"])
        self.assertIsNone(fact["team1"]["players"][0]["game_score"])
        self.assertIsNone(fact["team1"]["players"][0]["score_source"])
        self.assertFalse(fact["team1"]["score_complete"])
        self.assertEqual(fact["team1"]["score_count"], 2)
        self.assertIsNone(fact["team1"]["score_avg"])
        self.assertIsNone(fact["min_team_score_sum"])
        self.assertIsNone(fact["max_team_score_sum"])

    def test_explicit_non_3v3_or_bad_structure_becomes_a_tombstone_with_no_query_fields(self) -> None:
        cases: List[Dict[str, Any]] = []
        non_3v3 = make_payload()
        detail_of(non_3v3)["basic_info"]["match_type"] = 2
        cases.append(non_3v3)
        wrong_team_size = make_payload()
        detail_of(wrong_team_size)["team2"]["players_info"].pop()
        cases.append(wrong_team_size)
        bad_kungfu = make_payload()
        detail_of(bad_kungfu)["team1"]["players_info"][0]["kungfu_id"] = 0
        cases.append(bad_kungfu)
        bad_winner = make_payload()
        detail_of(bad_winner)["team2"]["won"] = True
        cases.append(bad_winner)
        missing_time = make_payload()
        del detail_of(missing_time)["match_time"]
        detail_of(missing_time)["basic_info"] = {"match_type": 3}
        cases.append(missing_time)

        for payload in cases:
            with self.subTest(payload=payload):
                fact = build_match_fact(123, payload, 1)
                self.assertFalse(fact["active"])
                self.assertIsInstance(fact["invalid_reason"], str)
                self.assertTrue(fact["source_hash"])
                self.assertEqual(
                    set(fact),
                    {"match_id", "active", "invalid_reason", "schema_version", "source_cached_at", "source_hash"},
                )

    def test_unavailable_becomes_a_tombstone(self) -> None:
        payload = make_payload()
        payload["data"]["unavailable"] = True

        fact = build_match_fact(123, payload, 1)

        self.assertFalse(fact["active"])
        self.assertEqual(fact["invalid_reason"], "unavailable")
        self.assertEqual(
            set(fact),
            {"match_id", "active", "invalid_reason", "schema_version", "source_cached_at", "source_hash"},
        )

    def test_illegal_match_id_raises_value_error(self) -> None:
        for match_id in (0, -1, True, "01", "bad"):
            with self.subTest(match_id=match_id):
                with self.assertRaises(ValueError):
                    build_match_fact(match_id, make_payload(), 1)

    def test_illegal_schema_version_raises_value_error(self) -> None:
        for schema_version in (0, -1, True, 1.5, "1"):
            with self.subTest(schema_version=schema_version):
                with self.assertRaises(ValueError):
                    build_match_fact(123, make_payload(), schema_version)

    def test_source_cached_at_keeps_positive_finite_version_watermark(self) -> None:
        for cached_at, expected in (
            (1700000200, 1700000200),
            (1700000200.25, 1700000200.25),
        ):
            with self.subTest(cached_at=cached_at):
                payload = make_payload(cached_at=cached_at)
                self.assertEqual(build_match_fact(123, payload, 1)["source_cached_at"], expected)
        for cached_at in (True, False, 0, -1, math.nan, math.inf, -math.inf, "0", "1", "1700000200.25", "nan"):
            with self.subTest(cached_at=cached_at):
                payload = make_payload(cached_at=cached_at)
                self.assertIsNone(build_match_fact(123, payload, 1)["source_cached_at"])


class TestSourceHash(unittest.TestCase):
    def test_source_hash_is_canonical_utf8_compact_sorted_sha256_and_schema_stable(self) -> None:
        source = {"角色": "花间游", "items": [3, 1], "nested": {"b": 2, "a": 1}}
        expected = hashlib.sha256(
            json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(build_source_hash(source), expected)

        first = build_match_fact(123, make_payload(), 1)
        second = build_match_fact(123, make_payload(), 2)
        self.assertNotEqual(first["schema_version"], second["schema_version"])
        self.assertEqual(first["source_hash"], second["source_hash"])

    def test_source_hash_includes_only_the_normalized_source_summary(self) -> None:
        baseline = build_match_fact(123, make_payload(), 1)["source_hash"]

        irrelevant = make_payload()
        player = detail_of(irrelevant)["team1"]["players_info"][0]
        player["armors"] = [{"name": "不同装备"}]
        player["talents"] = [{"name": "不同奇穴"}]
        player["metrics"] = [{"name": "不同指标"}]
        detail_of(irrelevant)["replay"] = {"very": "different"}
        self.assertEqual(build_match_fact(123, irrelevant, 1)["source_hash"], baseline)

        changed_unused_score = make_payload()
        detail_of(changed_unused_score)["team1"]["players_info"][0]["score"] = 777
        self.assertNotEqual(build_match_fact(123, changed_unused_score, 1)["source_hash"], baseline)

        changed_role = make_payload()
        detail_of(changed_role)["team1"]["players_info"][0]["role_name"] = "不同角色"
        self.assertNotEqual(build_match_fact(123, changed_role, 1)["source_hash"], baseline)

    def test_source_hash_excludes_score_selection_derivatives(self) -> None:
        payload = make_payload()
        baseline = build_match_fact(123, payload, 1)
        original_select = jjc_match_fact._normalized_player_scores

        def select_score_instead(player: Dict[str, Any]) -> Any:
            total_score, score, _, _ = original_select(player)
            return total_score, score, score, "score"

        with patch(
            "src.services.jx3.jjc_match_fact._normalized_player_scores",
            side_effect=select_score_instead,
        ):
            changed = build_match_fact(123, payload, 1)

        self.assertNotEqual(changed["team1"]["players"][0]["game_score"], baseline["team1"]["players"][0]["game_score"])
        self.assertNotEqual(changed["team1"]["players"][0]["score_source"], baseline["team1"]["players"][0]["score_source"])
        self.assertEqual(changed["source_hash"], baseline["source_hash"])

    def test_every_declared_source_field_changes_the_hash(self) -> None:
        baseline = build_match_fact(123, make_payload(), 1)["source_hash"]
        cases = []

        changed_time = make_payload()
        changed_time["data"]["match_time"] = 1700000300
        cases.append(changed_time)
        changed_map = make_payload()
        detail_of(changed_map)["basic_info"]["map"] = "名剑大会"
        cases.append(changed_map)
        changed_duration = make_payload()
        detail_of(changed_duration)["basic_info"]["duration"] = 181
        cases.append(changed_duration)
        changed_type = make_payload()
        detail_of(changed_type)["basic_info"]["match_type"] = 2
        cases.append(changed_type)
        changed_won = make_payload()
        detail_of(changed_won)["team1"]["won"] = False
        cases.append(changed_won)
        changed_server = make_payload()
        detail_of(changed_server)["team1"]["players_info"][0]["server"] = "唯我独尊"
        cases.append(changed_server)
        changed_kungfu_id = make_payload()
        detail_of(changed_kungfu_id)["team1"]["players_info"][0]["kungfu_id"] = 10101
        cases.append(changed_kungfu_id)
        changed_kungfu = make_payload()
        detail_of(changed_kungfu)["team1"]["players_info"][0]["kungfu"] = "不同心法名"
        cases.append(changed_kungfu)
        changed_total_score = make_payload()
        detail_of(changed_total_score)["team1"]["players_info"][0]["total_score"] = 1001
        cases.append(changed_total_score)

        for payload in cases:
            with self.subTest(payload=payload):
                self.assertNotEqual(build_match_fact(123, payload, 1)["source_hash"], baseline)

        self.assertNotEqual(build_match_fact(124, make_payload(), 1)["source_hash"], baseline)
        unavailable = make_payload()
        unavailable["data"]["unavailable"] = True
        self.assertNotEqual(build_match_fact(123, unavailable, 1)["source_hash"], baseline)


if __name__ == "__main__":
    unittest.main()
