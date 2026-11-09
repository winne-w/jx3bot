from __future__ import annotations

import argparse
import copy
import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/rebuild_jjc_peak_score_rankings.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rebuild_peak_rankings_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRankingRepo:
    def __init__(self):
        self.anchors = [2000]
        self.summaries = {2000: {"current_season": "当前赛季"}}

    async def list_season_history(self, season):
        return {"items": [{"timestamp": anchor} for anchor in self.anchors]}

    async def load_summary(self, anchor):
        return self.summaries.get(anchor)


class FakePeakRepo:
    def __init__(self):
        self.docs = {}
        self.writes = []
        self.fail_type = None

    async def load_result(self, *, anchor_timestamp, score_type, **kwargs):
        return copy.deepcopy(self.docs.get((anchor_timestamp, score_type)))

    async def save_done(self, result):
        if result["score_type"] == self.fail_type:
            raise RuntimeError("secret-uri-or-role-name-must-not-leak")
        self.docs[result["anchor_timestamp"], result["score_type"]] = copy.deepcopy(result)
        self.writes.append(result)


class FakeParticipantRepo:
    def __init__(self):
        self.calls = []
        self.rows = [
            {"global_id": "private-a", "match_time": 999, "score": 3200, "match_id": 1},
            {"global_id": "private-old", "match_time": 999, "score": 3000, "match_id": 2},
            {"global_id": "private-a", "match_time": 1000, "score": 1800, "match_id": 3},
            {"global_id": "private-new", "match_time": 2000, "score": 1900, "match_id": 4},
            {"global_id": "private-future", "match_time": 2001, "score": 9900, "match_id": 5},
        ]

    async def aggregate_peak_scores(self, **kwargs):
        self.calls.append(kwargs)
        rows = [row for row in self.rows if kwargs["window_start"] <= row["match_time"] <= kwargs["window_end"]]
        by_id = {}
        for row in sorted(rows, key=lambda item: item["score"], reverse=True):
            by_id.setdefault(row["global_id"], row)
        items = [dict(row, rank=rank) for rank, row in enumerate(by_id.values(), 1)]
        return {"items": items, "item_count": len(items), "source_match_count": len(rows),
                "source_participant_count": len(rows)}


class RebuildPeakRankingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_module()
        self.ranking = FakeRankingRepo()
        self.peak = FakePeakRepo()
        self.participants = FakeParticipantRepo()
        self.database = object()
        self.module.get_current_season_config = lambda: {"current_season": "当前赛季", "season_start_time": 1000}
        self.module.JjcRankingStatsRepo = lambda **kwargs: self.ranking
        self.module.JjcPeakScoreRankingRepo = lambda **kwargs: self.peak
        self.module.JjcMatchParticipantRepo = lambda **kwargs: self.participants

    def args(self, mode="dry-run", anchors=None, season="当前赛季"):
        return argparse.Namespace(mode=mode, anchor=anchors or [], season=season)

    def seed_old_results(self):
        for score_type in ("game", "tuilan"):
            self.peak.docs[2000, score_type] = {"status": "done", "items": [
                {"global_id": "private-a", "match_time": 999, "score": 3200},
                {"global_id": "private-old", "match_time": 999, "score": 3000},
            ], "item_count": 2}

    async def test_dry_run_recomputes_both_scores_without_writing_or_disclosing_roles(self):
        self.seed_old_results()
        before = copy.deepcopy(self.peak.docs)
        report = await self.module.run(self.args(), self.database)
        self.assertEqual(report["completed"], 2)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(len(self.participants.calls), 2)
        self.assertEqual(self.peak.writes, [])
        self.assertEqual(self.peak.docs, before)
        for row in report["results"]:
            self.assertEqual(row["window_start"], 1000)
            self.assertEqual(row["old_preseason_peak_count"], 2)
            self.assertEqual(row["new_item_count"], 2)
            self.assertEqual(row["added_member_count"], 1)
            self.assertEqual(row["removed_member_count"], 1)
            self.assertEqual(row["changed_score_count"], 1)
        self.assertNotIn("private-", json.dumps(report))

    async def test_apply_rebuilds_then_verify_is_read_only(self):
        self.seed_old_results()
        applied = await self.module.run(self.args("apply"), self.database)
        self.assertEqual(applied["failed"], 0)
        self.assertEqual(len(self.peak.writes), 2)
        self.assertEqual([item["score"] for item in self.peak.docs[2000, "game"]["items"]], [1900, 1800])
        verified = await self.module.run(self.args("verify"), self.database)
        self.assertEqual(verified["failed"], 0)
        self.assertEqual(verified["completed"], 2)
        self.assertEqual(len(self.peak.writes), 2)
        self.assertEqual(len(self.participants.calls), 2)

    async def test_verify_rejects_old_done_results(self):
        self.seed_old_results()
        report = await self.module.run(self.args("verify"), self.database)
        self.assertEqual(report["failed"], 2)
        self.assertEqual(self.module.exit_code_for_report(report), 1)
        self.assertIn("result_contract_mismatch", report["results"][0]["errors"])
        self.assertIn("match_outside_window", report["results"][0]["errors"])
        self.assertEqual(self.peak.writes, [])
        self.assertEqual(self.participants.calls, [])

    async def test_selection_fully_validated_before_any_apply_write(self):
        self.ranking.anchors.append(1500)
        self.ranking.summaries[1500] = {"current_season": "错误赛季"}
        with self.assertRaisesRegex(ValueError, "snapshot_season_mismatch"):
            await self.module.run(self.args("apply"), self.database)
        self.assertEqual(self.peak.writes, [])

    async def test_explicit_anchor_must_belong_to_selected_season(self):
        with self.assertRaisesRegex(ValueError, "requested_anchor_not_in_season_history"):
            await self.module.run(self.args("apply", [2500]), self.database)
        self.assertEqual(self.peak.writes, [])

    async def test_preseason_history_anchor_and_other_season_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "only_configured_current_season"):
            await self.module.run(self.args(season="旧赛季"), self.database)
        self.ranking.anchors.append(999)
        with self.assertRaisesRegex(ValueError, "invalid_season_history_anchor"):
            await self.module.run(self.args("apply"), self.database)
        self.assertEqual(self.peak.writes, [])

    async def test_apply_write_failure_returns_nonzero_and_preserves_existing_document(self):
        self.seed_old_results()
        old_game = copy.deepcopy(self.peak.docs[2000, "game"])
        self.peak.fail_type = "game"
        report = await self.module.run(self.args("apply"), self.database)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(self.module.exit_code_for_report(report), 1)
        self.assertEqual(self.peak.docs[2000, "game"], old_game)
        self.assertNotIn("secret-uri", json.dumps(report))

    async def test_verify_detects_bad_count_rank_and_future_match(self):
        await self.module.run(self.args("apply"), self.database)
        game = self.peak.docs[2000, "game"]
        game["item_count"] = 99
        game["items"][0]["rank"] = 3
        game["items"][0]["match_time"] = 2001
        report = await self.module.run(self.args("verify"), self.database)
        game_row = next(row for row in report["results"] if row["score_type"] == "game")
        self.assertEqual(game_row["errors"], ["item_count_mismatch", "match_outside_window", "rank_not_contiguous"])

    async def test_repeated_apply_overwrites_same_two_keys_without_duplicate_results(self):
        await self.module.run(self.args("apply", [2000, 2000]), self.database)
        await self.module.run(self.args("apply", [2000]), self.database)
        self.assertEqual(len(self.peak.docs), 2)
        self.assertEqual(len(self.peak.writes), 4)


class RebuildPeakCliTests(unittest.TestCase):
    def test_parser_defaults_to_read_only_preview(self):
        module = load_module()
        args = module.parse_args(["--season", "当前赛季", "--anchor", "2000", "--anchor", "1500"])
        self.assertEqual(args.mode, "dry-run")
        self.assertEqual(args.anchor, [2000, 1500])

    def test_explicit_mongo_environment_has_priority(self):
        module = load_module()
        with patch.dict(os.environ, {"MONGO_URI": "mongodb://explicit-environment/example"}):
            self.assertEqual(module.get_mongo_uri(), "mongodb://explicit-environment/example")

    def test_cli_reports_safe_validation_codes_and_hides_connection_errors(self):
        module = load_module()
        for error in (ValueError("snapshot_season_mismatch"), RuntimeError("mongodb://private-connection")):
            output = io.StringIO()
            with patch.object(module, "_run_connected", AsyncMock(side_effect=error)), patch("sys.stdout", output):
                self.assertEqual(module.main(["--season", "当前赛季"]), 1)
            report = json.loads(output.getvalue())
            if isinstance(error, ValueError):
                self.assertEqual(report["error"], "snapshot_season_mismatch")
            self.assertNotIn("private-connection", output.getvalue())


if __name__ == "__main__":
    unittest.main()
