from __future__ import annotations

import asyncio
import copy
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pymongo.errors import ExecutionTimeout

from src.services.jx3.jjc_peak_score_ranking import JjcPeakScoreRankingService
from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo


DAY = 86400
SEASON = "测试赛季"
SEASON_START = 1_000_000
ANCHOR = SEASON_START + 4 * DAY
SCOPE = "season_bounded_v1"


def valid_result(anchor: int = ANCHOR, score_type: str = "game", **changes: Any) -> Dict[str, Any]:
    result = {
        "anchor_timestamp": anchor,
        "window_start": max(anchor - 14 * DAY, SEASON_START),
        "window_end": anchor,
        "window_days": 14,
        "score_type": score_type,
        "version": 1,
        "status": "done",
        "aggregation_scope": SCOPE,
        "season_id": SEASON,
        "season_start_time": SEASON_START,
        "items": [{"rank": 1, "global_id": "g1", "score": 1800,
                   "match_id": 253860192, "match_time": anchor - 1,
                   "kungfu": "傲血战意", "match_count": 2}],
        "item_count": 1,
        "source_match_count": 2,
        "source_participant_count": 2,
    }
    result.update(changes)
    return result


class FakeRankingStatsRepo:
    def __init__(self, timestamps: Optional[List[int]] = None, season: Optional[str] = SEASON) -> None:
        self.timestamps = timestamps if timestamps is not None else [ANCHOR]
        self.season = season
        self.calls: List[Dict[str, Any]] = []
        self.summary_calls: List[int] = []

    async def list_timestamps(self, page: Optional[int] = None,
                              page_size: Optional[int] = None,
                              with_meta: bool = False) -> Dict[str, Any]:
        self.calls.append({"page": page, "page_size": page_size, "with_meta": with_meta})
        return {"items": [{"timestamp": item, "current_season": self.season}
                          for item in self.timestamps[: int(page_size or 20)]],
                "page": page or 1, "page_size": page_size or 20,
                "total": len(self.timestamps), "has_more": False}

    async def load_summary(self, timestamp: int) -> Optional[Dict[str, Any]]:
        self.summary_calls.append(timestamp)
        if timestamp not in self.timestamps:
            return None
        return {"timestamp": timestamp, "current_season": self.season}


class FakeParticipantRepo:
    def __init__(self, fail: bool = False, result_time: Any = None) -> None:
        self.fail = fail
        self.result_time = result_time
        self.calls: List[Dict[str, Any]] = []

    async def aggregate_peak_scores(self, *, window_start: int, window_end: int,
                                    score_type: str, max_items: Optional[int] = None,
                                    include_source_counts: bool = True) -> Dict[str, Any]:
        self.calls.append({"window_start": window_start, "window_end": window_end,
                           "score_type": score_type, "max_items": max_items,
                           "include_source_counts": include_source_counts})
        if self.fail:
            raise RuntimeError("aggregate_failed")
        return {"items": [{"rank": 1, "score": 1800, "match_id": 253860192,
                           "match_time": window_end - 1 if self.result_time is None else self.result_time, "global_id": "g1",
                           "kungfu": "傲血战意", "match_count": 2}],
                "item_count": 1, "source_match_count": 2, "source_participant_count": 2}


class FakePeakRepo:
    def __init__(self, doc: Optional[Dict[str, Any]] = None, *,
                 load_error: Optional[BaseException] = None, fail_save: bool = False) -> None:
        self.doc = copy.deepcopy(doc)
        self.load_error = load_error
        self.fail_save = fail_save
        self.calls: List[Dict[str, Any]] = []
        self.processing: List[Dict[str, Any]] = []
        self.done: List[Dict[str, Any]] = []
        self.failed: List[Dict[str, Any]] = []

    async def load_result(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        self.calls.append(kwargs)
        if self.load_error:
            raise self.load_error
        if self.doc is not None and any(self.doc.get(key) != kwargs[key]
                                        for key in ("anchor_timestamp", "score_type", "version")):
            return None
        return copy.deepcopy(self.doc)

    async def mark_processing(self, **kwargs: Any) -> None:
        self.processing.append(kwargs)

    async def save_done(self, result: Dict[str, Any]) -> None:
        if self.fail_save:
            raise RuntimeError("save_failed")
        self.done.append(copy.deepcopy(result))
        self.doc = copy.deepcopy(result)

    async def mark_failed(self, **kwargs: Any) -> None:
        self.failed.append(kwargs)


class FakePeakCollection:
    def __init__(self, status: Optional[str]) -> None:
        self.status = status
        self.calls: List[Any] = []

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None,
                       **kwargs: Any) -> Optional[Dict[str, Any]]:
        self.calls.append({"query": query, "projection": projection, "kwargs": kwargs})
        if self.status is None:
            return None
        return {"status": self.status}


class FakePeakDb:
    def __init__(self, status: Optional[str]) -> None:
        self.jjc_peak_score_rankings = FakePeakCollection(status)


class TestJjcPeakScoreRankingService(unittest.IsolatedAsyncioTestCase):
    def service(self, *, ranking_repo: Optional[FakeRankingStatsRepo] = None,
                participant_repo: Optional[FakeParticipantRepo] = None,
                peak_repo: Optional[FakePeakRepo] = None,
                **kwargs: Any) -> JjcPeakScoreRankingService:
        return JjcPeakScoreRankingService(
            ranking_stats_repo=ranking_repo or FakeRankingStatsRepo(),
            participant_repo=participant_repo or FakeParticipantRepo(),
            peak_repo=peak_repo or FakePeakRepo(),
            current_season=SEASON, season_start_time=SEASON_START, **kwargs)

    async def test_uses_latest_two_snapshot_timestamps_as_anchors(self) -> None:
        ranking_repo = FakeRankingStatsRepo([ANCHOR, ANCHOR - DAY, ANCHOR - 2 * DAY])
        participant_repo = FakeParticipantRepo()
        service = self.service(ranking_repo=ranking_repo, participant_repo=participant_repo)
        result = await service.run_latest_two_snapshots()
        self.assertEqual(result["anchors"], [ANCHOR, ANCHOR - DAY])
        self.assertEqual(len(participant_repo.calls), 4)
        self.assertEqual({(c["window_end"], c["score_type"]) for c in participant_repo.calls},
                         {(ANCHOR, "tuilan"), (ANCHOR, "game"),
                          (ANCHOR - DAY, "tuilan"), (ANCHOR - DAY, "game")})
        self.assertEqual(result["generated"], 4)
        self.assertTrue(all(c["window_start"] == SEASON_START for c in participant_repo.calls))

    async def test_first_four_days_are_clipped_to_season_start(self) -> None:
        peak_repo = FakePeakRepo()
        service = self.service(peak_repo=peak_repo)
        result = await service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["window_start"], SEASON_START)
        self.assertEqual(result["window_end"], ANCHOR)
        self.assertEqual(result["aggregation_scope"], SCOPE)
        self.assertEqual(result["season_id"], SEASON)
        self.assertEqual(result["season_start_time"], SEASON_START)
        self.assertEqual(result["items"][0]["match_id"], 253860192)
        self.assertEqual(peak_repo.done[0]["items"][0]["match_time"], ANCHOR - 1)
        self.assertEqual(peak_repo.processing, [])

    async def test_mature_season_retains_rolling_fourteen_day_window(self) -> None:
        anchor = SEASON_START + 30 * DAY
        service = self.service(ranking_repo=FakeRankingStatsRepo([anchor]))
        result = await service.generate_for_anchor(anchor_timestamp=anchor, score_type="tuilan")
        self.assertEqual(result["window_start"], anchor - 14 * DAY)
        self.assertEqual(result["window_end"], anchor)

    async def test_skips_only_valid_season_bounded_done_result(self) -> None:
        participant_repo = FakeParticipantRepo()
        peak_repo = FakePeakRepo(valid_result(score_type="tuilan"))
        service = self.service(participant_repo=participant_repo, peak_repo=peak_repo)
        result = await service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="tuilan")
        self.assertTrue(result["skipped"])
        self.assertEqual(participant_repo.calls, [])
        self.assertEqual(peak_repo.processing, [])
        self.assertEqual(peak_repo.done, [])

    async def test_legacy_current_done_result_does_not_suppress_rebuild(self) -> None:
        legacy = valid_result()
        for field in ("aggregation_scope", "season_id", "season_start_time"):
            legacy.pop(field)
        legacy["window_start"] = ANCHOR - 14 * DAY
        participant_repo = FakeParticipantRepo()
        peak_repo = FakePeakRepo(legacy)
        result = await self.service(participant_repo=participant_repo, peak_repo=peak_repo).generate_for_anchor(
            anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(result["status"], "done")
        self.assertFalse(result.get("skipped", False))
        self.assertEqual(participant_repo.calls[0]["window_start"], SEASON_START)
        self.assertEqual(len(peak_repo.done), 1)

    async def test_wrong_cache_metadata_cannot_be_reused(self) -> None:
        cases = [{"aggregation_scope": "old"}, {"season_id": "其他赛季"},
                 {"season_start_time": SEASON_START - DAY},
                 {"window_start": SEASON_START - 1}, {"window_end": ANCHOR + 1},
                 {"status": "failed"}, {"version": 2}]
        for change in cases:
            with self.subTest(change=change):
                participants = FakeParticipantRepo()
                service = self.service(participant_repo=participants,
                                       peak_repo=FakePeakRepo(valid_result(**change)))
                result = await service.load_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
                self.assertIsNotNone(result)
                self.assertEqual(len(participants.calls), 1)
                self.assertEqual(result["aggregation_scope"], SCOPE)
                self.assertEqual(result["window_start"], SEASON_START)

    async def test_read_fallback_is_read_only_and_keeps_same_window(self) -> None:
        participants = FakeParticipantRepo()
        peak_repo = FakePeakRepo()
        result = await self.service(participant_repo=participants, peak_repo=peak_repo).load_for_anchor(
            anchor_timestamp=ANCHOR, score_type="game", max_items=50)
        self.assertIsNotNone(result)
        self.assertEqual(result["window_start"], SEASON_START)
        self.assertEqual(participants.calls[0]["max_items"], 50)
        self.assertEqual(peak_repo.done, [])
        self.assertEqual(peak_repo.processing, [])

    async def test_cache_timeout_fallback_still_clips_to_season(self) -> None:
        participants = FakeParticipantRepo()

        async def timeout_wait(coroutine: Any, *, timeout: float) -> Any:
            self.assertEqual(timeout, 2.0)
            coroutine.close()
            raise asyncio.TimeoutError()

        with patch("src.services.jx3.jjc_peak_score_ranking.asyncio.wait_for", timeout_wait):
            result = await self.service(participant_repo=participants).load_for_anchor(
                anchor_timestamp=ANCHOR, score_type="game")
        self.assertIsNotNone(result)
        self.assertEqual(participants.calls[0]["window_start"], SEASON_START)

    async def test_mongo_execution_timeout_uses_season_bounded_read_fallback(self) -> None:
        participants = FakeParticipantRepo()
        peak_repo = FakePeakRepo(load_error=ExecutionTimeout("query exceeded time limit"))
        result = await self.service(participant_repo=participants, peak_repo=peak_repo).load_for_anchor(
            anchor_timestamp=ANCHOR, score_type="game")
        self.assertIsNotNone(result)
        self.assertTrue(result["fallback_aggregate"])
        self.assertEqual(result["window_start"], SEASON_START)
        self.assertEqual(participants.calls[0]["window_start"], SEASON_START)
        self.assertEqual(peak_repo.done, [])

    async def test_generation_redacts_untrusted_exception_messages_from_result_and_log(self) -> None:
        synthetic_uri = "mongodb://{}:{}@database.invalid/".format(uuid4().hex, uuid4().hex)
        for exception in (RuntimeError(synthetic_uri), ValueError(synthetic_uri)):
            with self.subTest(exception=type(exception).__name__):
                participants = FakeParticipantRepo()
                participants.aggregate_peak_scores = AsyncMock(side_effect=exception)
                with patch("src.services.jx3.jjc_peak_score_ranking.logger.warning") as warning:
                    result = await self.service(participant_repo=participants).generate_for_anchor(
                        anchor_timestamp=ANCHOR, score_type="game")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"], type(exception).__name__)
                self.assertNotIn(synthetic_uri, str(result))
                self.assertNotIn(synthetic_uri, str(warning.call_args_list))

    async def test_generation_preserves_known_safe_domain_failure_code(self) -> None:
        result = await self.service(ranking_repo=FakeRankingStatsRepo([])).generate_for_anchor(
            anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "unknown_or_invalid_snapshot_season")
    async def test_missing_summary_does_not_aggregate_arbitrary_timestamp(self) -> None:
        participants = FakeParticipantRepo()
        service = self.service(ranking_repo=FakeRankingStatsRepo([]), participant_repo=participants)
        result = await service.load_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertIsNone(result)
        self.assertEqual(participants.calls, [])

    async def test_current_season_summary_before_opening_is_rejected(self) -> None:
        anchor = SEASON_START - 1
        participants = FakeParticipantRepo()
        service = self.service(ranking_repo=FakeRankingStatsRepo([anchor]), participant_repo=participants)
        result = await service.load_for_anchor(anchor_timestamp=anchor, score_type="game")
        self.assertIsNone(result)
        self.assertEqual(participants.calls, [])

    async def test_legacy_history_is_preserved_without_current_cutoff(self) -> None:
        anchor = SEASON_START - DAY
        legacy = {"anchor_timestamp": anchor, "window_start": anchor - 14 * DAY,
                  "window_end": anchor, "score_type": "game", "version": 1,
                  "status": "done", "items": [{"score": 3200, "match_time": anchor - 1}],
                  "item_count": 1}
        participants = FakeParticipantRepo()
        service = self.service(ranking_repo=FakeRankingStatsRepo([anchor], season="旧赛季"),
                               participant_repo=participants, peak_repo=FakePeakRepo(legacy))
        result = await service.load_for_anchor(anchor_timestamp=anchor, score_type="game")
        self.assertEqual(result["window_start"], anchor - 14 * DAY)
        self.assertEqual(result["items"][0]["score"], 3200)
        self.assertEqual(participants.calls, [])

    async def test_history_without_known_boundary_and_result_does_not_guess(self) -> None:
        anchor = SEASON_START - DAY
        participants = FakeParticipantRepo()
        service = self.service(ranking_repo=FakeRankingStatsRepo([anchor], season="旧赛季"),
                               participant_repo=participants)
        result = await service.load_for_anchor(anchor_timestamp=anchor, score_type="game")
        self.assertIsNone(result)
        self.assertEqual(participants.calls, [])

    async def test_corrected_history_keeps_its_persisted_boundary_after_season_change(self) -> None:
        old = valid_result(season_id="旧赛季")
        participants = FakeParticipantRepo()
        service = JjcPeakScoreRankingService(
            ranking_stats_repo=FakeRankingStatsRepo([ANCHOR], season="旧赛季"),
            participant_repo=participants, peak_repo=FakePeakRepo(old),
            current_season="更新赛季", season_start_time=ANCHOR + 30 * DAY)
        result = await service.load_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(result["season_id"], "旧赛季")
        self.assertEqual(result["season_start_time"], SEASON_START)
        self.assertEqual(result["window_start"], SEASON_START)
        self.assertEqual(participants.calls, [])

    async def test_force_rebuild_replaces_valid_result_only_after_success(self) -> None:
        peak_repo = FakePeakRepo(valid_result())
        result = await self.service(peak_repo=peak_repo).generate_for_anchor(
            anchor_timestamp=ANCHOR, score_type="game", force=True)
        self.assertEqual(result["status"], "done")
        self.assertFalse(result.get("skipped", False))
        self.assertEqual(len(peak_repo.done), 1)
        self.assertEqual(peak_repo.processing, [])

    async def test_aggregate_failure_does_not_destroy_valid_saved_result(self) -> None:
        old = valid_result()
        peak_repo = FakePeakRepo(old)
        result = await self.service(peak_repo=peak_repo,
                                    participant_repo=FakeParticipantRepo(fail=True)).generate_for_anchor(
            anchor_timestamp=ANCHOR, score_type="game", force=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "RuntimeError")
        self.assertEqual(peak_repo.doc, old)
        self.assertEqual(peak_repo.processing, [])
        self.assertEqual(peak_repo.done, [])
        self.assertEqual(peak_repo.failed, [])

    async def test_save_failure_is_not_reported_as_generated_and_preserves_previous_result(self) -> None:
        old = valid_result()
        peak_repo = FakePeakRepo(old, fail_save=True)
        result = await self.service(peak_repo=peak_repo).generate_for_anchor(
            anchor_timestamp=ANCHOR, score_type="game", force=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "RuntimeError")
        self.assertEqual(peak_repo.doc, old)
        self.assertEqual(peak_repo.failed, [])

    async def test_failed_read_aggregation_does_not_fall_back_to_legacy_current_scores(self) -> None:
        legacy = valid_result(aggregation_scope="old")
        peak_repo = FakePeakRepo(legacy)
        service = self.service(peak_repo=peak_repo, participant_repo=FakeParticipantRepo(fail=True))
        try:
            result = await service.load_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        except RuntimeError as exc:
            self.assertEqual(str(exc), "aggregate_failed")
        else:
            self.assertTrue(result is None or result.get("status") != "done")
        self.assertEqual(peak_repo.doc, legacy)

    async def test_publishing_rejects_out_of_range_or_invalid_match_times(self) -> None:
        for match_time in (SEASON_START - 1, ANCHOR + 1, "1345599", True):
            with self.subTest(match_time=match_time):
                peak_repo = FakePeakRepo()
                service = self.service(peak_repo=peak_repo,
                                       participant_repo=FakeParticipantRepo(result_time=match_time))
                result = await service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(peak_repo.done, [])

    async def test_opening_second_and_anchor_second_are_valid(self) -> None:
        for match_time in (SEASON_START, ANCHOR):
            with self.subTest(match_time=match_time):
                service = self.service(participant_repo=FakeParticipantRepo(result_time=match_time))
                result = await service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
                self.assertEqual(result["status"], "done")
                self.assertEqual(result["items"][0]["match_time"], match_time)

    async def test_repeated_generation_reuses_completed_valid_result(self) -> None:
        peak_repo = FakePeakRepo()
        participant_repo = FakeParticipantRepo()
        service = self.service(peak_repo=peak_repo, participant_repo=participant_repo)
        first = await service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        second = await service.generate_for_anchor(anchor_timestamp=ANCHOR, score_type="game")
        self.assertEqual(first["status"], "done")
        self.assertTrue(second["skipped"])
        self.assertEqual(len(peak_repo.done), 1)
        self.assertEqual(len(participant_repo.calls), 1)

    async def test_is_done_uses_lightweight_status_lookup(self) -> None:
        repo = JjcPeakScoreRankingRepo(db=FakePeakDb("done"))
        done = await repo.is_done(anchor_timestamp=2000, score_type="game", version=1)
        self.assertTrue(done)
        self.assertEqual(repo.db.jjc_peak_score_rankings.calls, [{
            "query": {"anchor_timestamp": 2000, "score_type": "game", "version": 1},
            "projection": {"_id": 0, "status": 1}, "kwargs": {}}])

    async def test_is_done_returns_false_when_not_done(self) -> None:
        repo = JjcPeakScoreRankingRepo(db=FakePeakDb("processing"))
        self.assertFalse(await repo.is_done(anchor_timestamp=3000, score_type="tuilan", version=1))

    async def test_is_done_returns_false_when_missing(self) -> None:
        repo = JjcPeakScoreRankingRepo(db=FakePeakDb(None))
        self.assertFalse(await repo.is_done(anchor_timestamp=4000, score_type="game", version=1))


if __name__ == "__main__":
    unittest.main()