"""Season peak-score aggregation against an explicitly isolated local MongoDB."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any, Dict, List
import unittest
from uuid import uuid4

from bson.int64 import Int64
from motor.motor_asyncio import AsyncIOMotorClient

from src.services.jx3.jjc_peak_score_ranking import JjcPeakScoreRankingService
from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo
from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo
from tests.test_jjc_kungfu_refresh_mongo import checked_test_uri


SEASON = "隔离测试赛季"
START = int(datetime.fromisoformat("2026-11-05T00:00:00+08:00").timestamp())
ANCHOR = START + 4 * 86400


class SummaryRepo:
    async def load_summary(self, timestamp: int) -> Dict[str, Any]:
        return {"timestamp": timestamp, "current_season": SEASON}


def participant(global_id: str, match_id: int, match_time: Any,
                game_score: Any, tuilan_score: Any, **changes: Any) -> Dict[str, Any]:
    row = {"global_id": global_id, "match_id": match_id, "match_time": match_time,
           "game_score": game_score, "tuilan_score": tuilan_score,
           "game_score_source": "total_score", "match_type": 3,
           "detail_available": True, "role_name": global_id,
           "server": "测试服", "kungfu": "傲血战意", "kungfu_id": "10026"}
    row.update(changes)
    return row


class RecordingCollection:
    def __init__(self, collection: Any) -> None:
        self.collection = collection
        self.pipeline: List[Dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.collection, name)

    def aggregate(self, pipeline: List[Dict[str, Any]], **kwargs: Any) -> Any:
        self.pipeline = pipeline
        return self.collection.aggregate(pipeline, **kwargs)


def index_names(value: Any) -> List[str]:
    names: List[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("indexName"), str):
            names.append(value["indexName"])
        for child in value.values():
            names.extend(index_names(child))
    elif isinstance(value, list):
        for child in value:
            names.extend(index_names(child))
    return sorted(set(names))


def winning_index_names(value: Any) -> List[str]:
    names: List[str] = []
    if isinstance(value, dict):
        if "winningPlan" in value:
            names.extend(index_names(value["winningPlan"]))
        for key, child in value.items():
            if key not in {"winningPlan", "rejectedPlans", "allPlansExecution"}:
                names.extend(winning_index_names(child))
    elif isinstance(value, list):
        for child in value:
            names.extend(winning_index_names(child))
    return sorted(set(names))

@unittest.skipUnless(os.environ.get("JJC_TEST_MONGO_URI"), "explicit local Mongo URI required")
class TestPeakScoreSeasonMongo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.uri = checked_test_uri(os.environ["JJC_TEST_MONGO_URI"])
        self.db_name = "jjc_peak_season_test_" + uuid4().hex
        self.client = AsyncIOMotorClient(self.uri, serverSelectionTimeoutMS=3000)
        await self.client.admin.command("ping")
        self.db = self.client[self.db_name]
        self.participants = self.db.jjc_match_participants
        for score in ("game", "tuilan"):
            await self.participants.create_index(
                [("match_type", 1), ("detail_available", 1), ("match_time", 1),
                 (score + "_score", -1)], name="idx_available_time_" + score + "_score")
        await self.db.jjc_peak_score_rankings.create_index(
            [("anchor_timestamp", 1), ("score_type", 1), ("version", 1)], unique=True)
        rows = [
            participant("shared", 1, START - 1, 3200, 3400),
            participant("old_only", 2, START - 1, 3300, 3500),
            participant("shared", 101, START + 1, 1800, 2000),
            participant("shared", 102, ANCHOR - 1, 1700, 2100),
            participant("new_added", 101, START + 2, 1900, 1900),
            participant("opening", 103, START, 1500, 1600),
            participant("anchor", 104, ANCHOR, 1600, 1700),
            participant("future", 105, ANCHOR + 1, 9999, 9999),
            participant("missing_time", 106, None, 9999, 9999),
            participant("other_type", 107, START + 1, 9999, 9999, match_type=2),
            participant("no_detail", 108, START + 1, 9999, 9999, detail_available=False),
            participant("missing_score", 109, START + 1, None, None),
            participant("", 110, START + 1, 9999, 9999),
        ]
        # Older data makes the real planner's time-index selectivity measurable.
        rows.extend(participant("filler_" + str(i), 1000 + i,
                                START - 30 * 86400 - i, 3000, 3100)
                    for i in range(1500))
        await self.participants.insert_many(rows)
        self.peak_repo = JjcPeakScoreRankingRepo(db=self.db, suppress_errors=False)
        self.service = JjcPeakScoreRankingService(
            ranking_stats_repo=SummaryRepo(),
            participant_repo=JjcMatchParticipantRepo(db=self.db), peak_repo=self.peak_repo,
            current_season=SEASON, season_start_time=START)

    async def asyncTearDown(self) -> None:
        checked_test_uri(self.uri)
        self.assertTrue(self.db_name.startswith("jjc_peak_season_test_"))
        self.assertEqual(len(self.db_name), len("jjc_peak_season_test_") + 32)
        await self.client.drop_database(self.db_name)
        self.client.close()

    async def test_real_aggregate_replaces_old_peak_and_counts_only_current_rows(self) -> None:
        for score_type in ("game", "tuilan"):
            with self.subTest(score_type=score_type):
                result = await self.service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type=score_type)
                self.assertEqual(result["status"], "done")
                self.assertEqual(result["item_count"], 4)
                self.assertEqual(result["source_participant_count"], 5)
                self.assertEqual(result["source_match_count"], 4)
                self.assertEqual(result["window_start"], START)
                self.assertEqual(result["window_end"], ANCHOR)
                self.assertEqual({row["global_id"] for row in result["items"]},
                                 {"shared", "new_added", "opening", "anchor"})
                shared = next(row for row in result["items"] if row["global_id"] == "shared")
                self.assertEqual(shared["score"], 1800 if score_type == "game" else 2100)
                self.assertEqual(shared["match_id"], 101 if score_type == "game" else 102)
                self.assertEqual(shared["match_count"], 2)
                self.assertEqual([row["rank"] for row in result["items"]], [1, 2, 3, 4])
                self.assertTrue(all(START <= row["match_time"] <= ANCHOR for row in result["items"]))

    async def test_bson_long_match_time_is_a_valid_timestamp(self) -> None:
        await self.participants.insert_one(participant(
            "long_time", 111, Int64(START + 3), 2500, 2600))
        result = await self.service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["items"][0]["global_id"], "long_time")
        self.assertEqual(result["items"][0]["match_time"], START + 3)
    async def test_historical_bson_long_season_start_remains_readable(self) -> None:
        generated = await self.service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(generated["status"], "done")
        await self.db.jjc_peak_score_rankings.update_one(
            {"anchor_timestamp": ANCHOR, "score_type": "game", "version": 1},
            {"$set": {"season_start_time": Int64(START)}})
        next_season_service = JjcPeakScoreRankingService(
            ranking_stats_repo=SummaryRepo(), participant_repo=JjcMatchParticipantRepo(db=self.db),
            peak_repo=self.peak_repo, current_season="未来赛季", season_start_time=ANCHOR + 30 * 86400)
        result = await next_season_service.load_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertIsNotNone(result)
        self.assertFalse(result.get("fallback_aggregate", False))
        self.assertEqual(result["season_id"], SEASON)
        self.assertEqual(result["season_start_time"], START)
        self.assertEqual(result["window_start"], START)
        self.assertEqual(result["item_count"], 4)
    async def test_current_legacy_done_result_is_rebuilt_in_place(self) -> None:
        legacy = {"anchor_timestamp": ANCHOR, "score_type": "game", "version": 1,
                  "window_start": ANCHOR - 14 * 86400, "window_end": ANCHOR,
                  "window_days": 14, "status": "done", "item_count": 1,
                  "items": [{"global_id": "old_only", "score": 3300, "match_time": START - 1}]}
        inserted = await self.db.jjc_peak_score_rankings.insert_one(legacy)
        result = await self.service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(result["status"], "done")
        self.assertFalse(result.get("skipped", False))
        stored = await self.db.jjc_peak_score_rankings.find_one({"_id": inserted.inserted_id})
        self.assertEqual(stored["aggregation_scope"], "season_bounded_v1")
        self.assertEqual(stored["season_id"], SEASON)
        self.assertEqual(stored["season_start_time"], START)
        self.assertEqual(stored["item_count"], 4)
        self.assertEqual(await self.db.jjc_peak_score_rankings.count_documents({}), 1)

    async def test_repeated_forced_generation_has_one_result_per_score_type(self) -> None:
        for _ in range(2):
            for score_type in ("game", "tuilan"):
                result = await self.service.generate_for_anchor(
                    anchor_timestamp=ANCHOR, score_type=score_type, force=True)
                self.assertEqual(result["status"], "done")
        self.assertEqual(await self.db.jjc_peak_score_rankings.count_documents({}), 2)
        skipped = await self.service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertTrue(skipped["skipped"])

    async def test_read_fallback_reaggregates_without_persisting(self) -> None:
        result = await self.service.load_for_anchor(anchor_timestamp=ANCHOR, score_type="game", max_items=2)
        self.assertTrue(result["fallback_aggregate"])
        self.assertEqual([row["global_id"] for row in result["items"]], ["new_added", "shared"])
        self.assertEqual(await self.db.jjc_peak_score_rankings.count_documents({}), 0)

    async def test_sliced_cache_retains_season_metadata_and_avoids_fallback(self) -> None:
        await self.service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        result = await self.service.load_for_anchor(anchor_timestamp=ANCHOR, score_type="game", max_items=2)
        self.assertFalse(result.get("fallback_aggregate", False))
        self.assertEqual(result["aggregation_scope"], "season_bounded_v1")
        self.assertEqual(result["season_id"], SEASON)
        self.assertEqual(result["season_start_time"], START)
        self.assertEqual(result["window_start"], START)
        self.assertEqual(result["item_count"], 4)
        self.assertEqual(len(result["items"]), 2)

    async def test_real_pipeline_explain_uses_time_index_and_saves_evidence(self) -> None:
        records = []
        for score_type in ("game", "tuilan"):
            recorder = RecordingCollection(self.participants)
            repo = JjcMatchParticipantRepo(db=SimpleNamespace(jjc_match_participants=recorder))
            started = time.perf_counter()
            result = await repo.aggregate_peak_scores(window_start=START, window_end=ANCHOR,
                                                      score_type=score_type, max_items=1000)
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.assertEqual(result["item_count"], 4)
            self.assertEqual(recorder.pipeline[0]["$match"]["match_time"], {"$gte": START, "$lte": ANCHOR})
            explanation = await self.db.command({"explain": {
                "aggregate": "jjc_match_participants", "pipeline": recorder.pipeline,
                "cursor": {}, "allowDiskUse": True}, "verbosity": "executionStats"})
            indexes = winning_index_names(explanation)
            self.assertTrue(set(indexes) & {"idx_available_time_game_score", "idx_available_time_tuilan_score"})
            records.append({"score_type": score_type, "elapsed_ms": elapsed_ms,
                            "item_count": result["item_count"], "index_names": indexes,
                            "first_match": recorder.pipeline[0], "explain": explanation})
        evidence_dir = os.environ.get("JJC_TEST_EVIDENCE_DIR")
        if evidence_dir:
            output = Path(evidence_dir)
            output.mkdir(parents=True, exist_ok=True)
            (output / "peak-score-mongo-explain.json").write_text(json.dumps({
                "mongo_version": (await self.client.admin.command("buildInfo"))["version"],
                "fixture_rows": await self.participants.count_documents({}),
                "records": records}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()