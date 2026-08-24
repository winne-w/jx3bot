from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "backfill_jjc_match_participant_season.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("backfill_jjc_match_participant_season", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load season backfill script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestJjcMatchParticipantSeasonBackfill(unittest.TestCase):
    def test_assigns_configured_season_at_boundary(self) -> None:
        module = _load_script_module()

        update = module.build_season_update(
            match_time=1777228800,
            current_season="暗影千机",
            season_start_time=1777228800,
        )

        self.assertEqual(update, {"$set": {"season_id": "暗影千机"}})

    def test_unassigns_preseason_and_unknown_time(self) -> None:
        module = _load_script_module()

        self.assertEqual(
            module.build_season_update(1777228799, "暗影千机", 1777228800),
            {"$set": {"season_id": None}},
        )

    def test_returns_nonzero_when_backfill_has_write_failures(self) -> None:
        module = _load_script_module()

        self.assertEqual(module.exit_code_for_stats({"failed": 1}), 1)
        self.assertEqual(module.exit_code_for_stats({"failed": 0}), 0)
        self.assertEqual(
            module.build_season_update(None, "暗影千机", 1777228800),
            {"$set": {"season_id": None}},
        )

    def test_builds_server_side_current_and_unassigned_queries(self) -> None:
        module = _load_script_module()

        current_query, unassigned_query = module.build_season_queries("暗影千机", 1777228800)

        self.assertEqual(current_query["match_type"], 3)
        self.assertEqual(current_query["match_time"], {"$gte": 1777228800})
        self.assertEqual(unassigned_query["match_type"], 3)
        self.assertEqual(unassigned_query["$or"], [
            {"match_time": {"$lt": 1777228800}},
            {"match_time": None},
            {"match_time": {"$exists": False}},
        ])


if __name__ == "__main__":
    unittest.main()
