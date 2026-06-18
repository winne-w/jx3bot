from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from src.services.jx3.jjc_peak_score_ranking import JjcPeakScoreRankingService


class FakeRankingStatsRepo:
    def __init__(self, timestamps: List[int]) -> None:
        self.timestamps = timestamps
        self.calls: List[Dict[str, Any]] = []

    async def list_timestamps(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        with_meta: bool = False,
    ) -> Dict[str, Any]:
        self.calls.append({"page": page, "page_size": page_size, "with_meta": with_meta})
        return {
            "items": [{"timestamp": item} for item in self.timestamps[: int(page_size or 20)]],
            "page": page or 1,
            "page_size": page_size or 20,
            "total": len(self.timestamps),
            "has_more": False,
        }


class FakeParticipantRepo:
    def __init__(self, aggregate: Optional[Dict[str, Any]] = None, fail: bool = False) -> None:
        self.aggregate = aggregate or {
            "items": [
                {
                    "rank": 1,
                    "score": 2660,
                    "match_id": 253860192,
                    "match_time": 1777395376,
                    "score_source": "mmr",
                    "global_id": "g1",
                    "role_name": "衔羽·梦江南",
                    "server": "梦江南",
                    "kungfu": "傲血战意",
                    "match_count": 2,
                }
            ],
            "item_count": 1,
            "source_match_count": 2,
            "source_participant_count": 2,
        }
        self.fail = fail
        self.calls: List[Dict[str, Any]] = []

    async def aggregate_peak_scores(
        self,
        *,
        window_start: int,
        window_end: int,
        score_type: str,
        max_items: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.calls.append({
            "window_start": window_start,
            "window_end": window_end,
            "score_type": score_type,
            "max_items": max_items,
        })
        if self.fail:
            raise RuntimeError("aggregate_failed")
        return self.aggregate


class FakePeakRepo:
    def __init__(self, done_keys: Optional[set] = None) -> None:
        self.done_keys = done_keys or set()
        self.processing: List[Dict[str, Any]] = []
        self.done: List[Dict[str, Any]] = []
        self.failed: List[Dict[str, Any]] = []

    async def is_done(self, *, anchor_timestamp: int, score_type: str, version: int = 1) -> bool:
        return (anchor_timestamp, score_type, version) in self.done_keys

    async def mark_processing(self, **kwargs: Any) -> None:
        self.processing.append(kwargs)

    async def save_done(self, result: Dict[str, Any]) -> None:
        self.done.append(result)

    async def mark_failed(self, **kwargs: Any) -> None:
        self.failed.append(kwargs)


class TestJjcPeakScoreRankingService(unittest.IsolatedAsyncioTestCase):
    async def test_uses_latest_two_snapshot_timestamps_as_anchors(self) -> None:
        ranking_repo = FakeRankingStatsRepo([2000, 1000, 500])
        participant_repo = FakeParticipantRepo()
        peak_repo = FakePeakRepo()
        service = JjcPeakScoreRankingService(
            ranking_stats_repo=ranking_repo,
            participant_repo=participant_repo,
            peak_repo=peak_repo,
        )

        result = await service.run_latest_two_snapshots()

        self.assertEqual(result["anchors"], [2000, 1000])
        self.assertEqual(len(participant_repo.calls), 4)
        self.assertEqual(
            {(call["window_end"], call["score_type"]) for call in participant_repo.calls},
            {(2000, "tuilan"), (2000, "game"), (1000, "tuilan"), (1000, "game")},
        )
        self.assertEqual(participant_repo.calls[0]["window_start"], 2000 - 7 * 86400)

    async def test_skips_existing_done_result(self) -> None:
        participant_repo = FakeParticipantRepo()
        peak_repo = FakePeakRepo(done_keys={(2000, "tuilan", 1)})
        service = JjcPeakScoreRankingService(
            ranking_stats_repo=FakeRankingStatsRepo([2000]),
            participant_repo=participant_repo,
            peak_repo=peak_repo,
        )

        result = await service.generate_for_anchor(anchor_timestamp=2000, score_type="tuilan")

        self.assertTrue(result["skipped"])
        self.assertEqual(participant_repo.calls, [])
        self.assertEqual(peak_repo.processing, [])

    async def test_result_preserves_peak_match_identity(self) -> None:
        peak_repo = FakePeakRepo()
        service = JjcPeakScoreRankingService(
            ranking_stats_repo=FakeRankingStatsRepo([2000]),
            participant_repo=FakeParticipantRepo(),
            peak_repo=peak_repo,
        )

        result = await service.generate_for_anchor(anchor_timestamp=2000, score_type="tuilan")

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["items"][0]["score"], 2660)
        self.assertEqual(result["items"][0]["match_id"], 253860192)
        self.assertEqual(result["items"][0]["match_time"], 1777395376)
        self.assertEqual(peak_repo.done[0]["items"][0]["match_id"], 253860192)

    async def test_failure_marks_failed(self) -> None:
        peak_repo = FakePeakRepo()
        service = JjcPeakScoreRankingService(
            ranking_stats_repo=FakeRankingStatsRepo([2000]),
            participant_repo=FakeParticipantRepo(fail=True),
            peak_repo=peak_repo,
        )

        result = await service.generate_for_anchor(anchor_timestamp=2000, score_type="game")

        self.assertEqual(result["status"], "failed")
        self.assertIn("aggregate_failed", result["error"])
        self.assertEqual(peak_repo.failed[0]["anchor_timestamp"], 2000)
        self.assertEqual(peak_repo.failed[0]["score_type"], "game")


if __name__ == "__main__":
    unittest.main()
