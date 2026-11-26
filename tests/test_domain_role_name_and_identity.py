"""Unit and architecture-guard tests for domain role_name, role_identity, season, snapshots, and coerce."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from src.domain.role_identity import (
    classify_replay_player_match,
    split_replay_role_name,
)
from src.domain.role_name import split_display_name, strip_server_suffix
from src.domain.season import parse_season_start_timestamp
from src.domain.snapshots import (
    TALENT_SNAPSHOT_SCHEMA_VERSION,
    build_equipment_snapshot,
    build_talent_snapshot,
)
from src.services.jx3 import kungfu
from src.services.jx3 import match_detail_snapshots as legacy_snapshots
from src.services.jx3 import role_identity_matching as legacy_matching
from src.utils.coerce import (
    clean_id,
    coerce_float,
    coerce_int,
    normalize_text,
    pick_text,
    strip_mongo_id,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestRoleNameDomain(unittest.TestCase):
    def test_strip_server_suffix_preserves_dot_in_role_name(self) -> None:
        self.assertEqual(strip_server_suffix("星·辰·梦江南", "梦江南"), "星·辰")
        self.assertEqual(strip_server_suffix("星·辰·梦江南", "蝶恋花"), "星·辰·梦江南")
        self.assertEqual(strip_server_suffix("星·辰", "梦江南"), "星·辰")
        self.assertEqual(strip_server_suffix("星·辰·梦江南", ""), "星·辰·梦江南")
        self.assertEqual(strip_server_suffix("·梦江南", "梦江南"), "·梦江南")
        self.assertEqual(strip_server_suffix("  星·辰 · 梦江南  ", " 梦江南 "), "星·辰")
        self.assertEqual(strip_server_suffix(None, "梦江南"), "")

    def test_split_display_name_with_explicit_server_and_dot_names(self) -> None:
        self.assertEqual(split_display_name("星·辰·梦江南", "梦江南"), ("梦江南", "星·辰"))
        self.assertEqual(split_display_name("星·辰", "梦江南"), ("梦江南", "星·辰"))
        self.assertEqual(split_display_name("星·辰·梦江南", "蝶恋花"), ("蝶恋花", "星·辰·梦江南"))
        self.assertEqual(split_display_name("角色A", "梦江南"), ("梦江南", "角色A"))

    def test_split_display_name_without_server_splits_on_last_dot(self) -> None:
        self.assertEqual(split_display_name("星·辰·梦江南"), ("梦江南", "星·辰"))
        self.assertEqual(split_display_name("角色A·梦江南"), ("梦江南", "角色A"))
        self.assertEqual(split_display_name("角色A"), ("", "角色A"))
        self.assertEqual(
            split_display_name("星·辰", known_servers={"梦江南", "蝶恋花"}),
            ("", "星·辰"),
        )
        self.assertEqual(
            split_display_name("星·辰·梦江南", known_servers={"梦江南", "蝶恋花"}),
            ("梦江南", "星·辰"),
        )

    def test_kungfu_split_replay_role_name_handles_dot_names(self) -> None:
        self.assertEqual(kungfu._split_replay_role_name("星·辰·梦江南"), ("梦江南", "星·辰"))
        self.assertEqual(kungfu._split_replay_role_name("星·辰", "梦江南"), ("梦江南", "星·辰"))
        self.assertEqual(split_replay_role_name("星·辰·梦江南"), ("梦江南", "星·辰"))


class TestClassifyReplayPlayerMatch(unittest.TestCase):
    def test_strong_match_on_equal_role_id_without_conflict(self) -> None:
        player = {"role_id": "200", "role_name": "星·辰·梦江南"}
        self.assertEqual(
            classify_replay_player_match(
                player, role_id="200", role_name="星·辰", server="梦江南"
            ),
            "strong",
        )
        self.assertEqual(
            classify_replay_player_match(
                {"role_id": "200", "role_name": "星·辰"},
                role_id="200",
                role_name="星·辰",
                server="梦江南",
            ),
            "strong",
        )
        self.assertEqual(
            classify_replay_player_match({"role_id": "200"}, role_id="200"),
            "strong",
        )

    def test_explicit_role_id_conflict_strictly_rejects_same_name_fallback(self) -> None:
        player = {
            "role_id": "999",
            "global_role_id": "888888",
            "role_name": "星·辰·梦江南",
        }
        self.assertIsNone(
            classify_replay_player_match(
                player, role_id="200", role_name="星·辰", server="梦江南"
            )
        )
        self.assertFalse(
            kungfu._replay_player_matches_role(
                player, role_id="200", role_name="星·辰", server="梦江南"
            )
        )
        self.assertIsNone(
            kungfu.extract_global_id_from_match_replay(
                {"data": {"players": [player]}},
                role_id="200",
                role_name="星·辰",
                server="梦江南",
            )
        )

    def test_strong_match_rejects_name_or_server_conflict(self) -> None:
        player = {"role_id": "200", "role_name": "星·辰·蝶恋花"}
        self.assertIsNone(
            classify_replay_player_match(
                player, role_id="200", role_name="星·辰", server="梦江南"
            )
        )
        self.assertIsNone(
            classify_replay_player_match(
                {"role_id": "200", "role_name": "别人·梦江南"},
                role_id="200",
                role_name="星·辰",
                server="梦江南",
            )
        )

    def test_weak_name_only_match_when_role_id_missing_on_either_side(self) -> None:
        self.assertEqual(
            classify_replay_player_match(
                {"role_name": "星·辰·梦江南"},
                role_id="200",
                role_name="星·辰",
                server="梦江南",
            ),
            "weak_name_only",
        )
        self.assertEqual(
            classify_replay_player_match(
                {"role_id": "200", "role_name": "星·辰·梦江南"},
                role_id=None,
                role_name="星·辰",
                server="梦江南",
            ),
            "weak_name_only",
        )
        self.assertIsNone(
            classify_replay_player_match(
                {"role_name": "星·辰·蝶恋花"},
                role_id=None,
                role_name="星·辰",
                server="梦江南",
            )
        )

    def test_merge_replay_global_ids_respects_dot_name_and_role_id_conflict(self) -> None:
        detail = {
            "data": {
                "team1": {
                    "players_info": [
                        {"role_id": "200", "role_name": "星·辰", "server": "梦江南"},
                        {"role_id": "201", "role_name": "星·辰", "server": "梦江南"},
                    ]
                },
                "team2": {"players_info": []},
            }
        }
        replay = {
            "data": {
                "players": [
                    {"role_id": "200", "global_role_id": "10001", "role_name": "星·辰·梦江南"},
                ]
            }
        }
        kungfu.merge_replay_global_ids_into_match_detail(detail, replay)
        players = detail["data"]["team1"]["players_info"]
        self.assertEqual(players[0].get("global_id"), "10001")
        self.assertNotIn("global_id", players[1])


class TestSeasonSnapshotsAndCoerce(unittest.TestCase):
    def test_parse_season_start_timestamp_beijing_tz(self) -> None:
        # 2026-04-24 00:00:00 UTC+8 == 2026-04-23 16:00:00 UTC == 1776960000
        self.assertEqual(parse_season_start_timestamp("2026-04-24"), 1776960000)
        with self.assertRaises(ValueError):
            parse_season_start_timestamp("2026/04/24")

    def test_coerce_int_boundaries(self) -> None:
        self.assertIsNone(coerce_int(True))
        self.assertIsNone(coerce_int(False))
        self.assertIsNone(coerce_int(None))
        self.assertEqual(coerce_int(0), 0)
        self.assertEqual(coerce_int(42), 42)
        self.assertEqual(coerce_int(-7), -7)
        self.assertEqual(coerce_int(3.0), 3)
        self.assertIsNone(coerce_int(3.5))
        self.assertIsNone(coerce_int(float("nan")))
        self.assertIsNone(coerce_int(float("inf")))
        self.assertEqual(coerce_int("42"), 42)
        self.assertEqual(coerce_int(" -7 "), -7)
        self.assertEqual(coerce_int("3.0"), 3)
        self.assertIsNone(coerce_int("3.5"))
        self.assertIsNone(coerce_int(""))
        self.assertIsNone(coerce_int("   "))
        self.assertIsNone(coerce_int("abc"))
        self.assertIsNone(coerce_int("nan"))

    def test_other_coerce_helpers(self) -> None:
        self.assertIsNone(coerce_float(True))
        self.assertIsNone(coerce_float(float("inf")))
        self.assertEqual(coerce_float("3.25"), 3.25)
        self.assertEqual(normalize_text("  AbC "), "abc")
        self.assertEqual(clean_id(" 123 "), "123")
        self.assertIsNone(clean_id("   "))
        self.assertIsNone(clean_id(False))
        self.assertEqual(pick_text(None, "  ", "ok", "later"), "ok")
        self.assertIsNone(pick_text(None, ""))
        doc = {"_id": "abc", "x": 1}
        stripped = strip_mongo_id(doc)
        self.assertEqual(stripped, {"x": 1})
        self.assertIn("_id", doc)
        self.assertIsNone(strip_mongo_id(None))

    def test_legacy_reexports_match_domain_symbols(self) -> None:
        self.assertIs(legacy_matching.classify_replay_player_match, classify_replay_player_match)
        self.assertEqual(legacy_snapshots.TALENT_SNAPSHOT_SCHEMA_VERSION, TALENT_SNAPSHOT_SCHEMA_VERSION)
        self.assertIs(legacy_snapshots.build_equipment_snapshot, build_equipment_snapshot)
        self.assertIs(legacy_snapshots.build_talent_snapshot, build_talent_snapshot)


def _iter_imported_modules(py_file: Path):
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module


class TestArchitectureBoundaries(unittest.TestCase):
    def test_storage_does_not_import_services(self) -> None:
        storage_dir = PROJECT_ROOT / "src" / "storage"
        violations = []
        for py_file in sorted(storage_dir.rglob("*.py")):
            for mod in _iter_imported_modules(py_file):
                if mod == "src.services" or mod.startswith("src.services."):
                    violations.append((str(py_file.relative_to(PROJECT_ROOT)), mod))
        self.assertEqual(violations, [], f"src/storage must not import src.services: {violations}")

    def test_domain_does_not_import_forbidden_layers(self) -> None:
        domain_dir = PROJECT_ROOT / "src" / "domain"
        forbidden_prefixes = (
            "src.services",
            "src.storage",
            "src.infra",
            "src.plugins",
            "src.api",
            "plugins",
            "api",
            "services",
            "storage",
            "infra",
            "nonebot",
            "motor",
            "pymongo",
            "config",
        )
        violations = []
        for py_file in sorted(domain_dir.rglob("*.py")):
            for mod in _iter_imported_modules(py_file):
                if any(mod == prefix or mod.startswith(prefix + ".") for prefix in forbidden_prefixes):
                    violations.append((str(py_file.relative_to(PROJECT_ROOT)), mod))
        self.assertEqual(violations, [], f"src/domain has forbidden imports: {violations}")


if __name__ == "__main__":
    unittest.main()
