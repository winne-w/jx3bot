from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional

from scripts import rebuild_jjc_projections
from src.services.jx3.jjc_match_data_sync import is_tuilan_auth_error
from src.services.jx3.jjc_ranking_stats_query import (
    build_peak_kungfu_statistics,
    load_peak_score_doc,
    normalize_optional_text,
)
from src.services.jx3.match_detail_persistence import MatchDetailPersistenceService


class _FakeInspectRepo:
    async def save_match_detail(self, match_id: Any, payload: Dict[str, Any]) -> bool:
        return True


class _FakeStageProjector:
    def __init__(
        self,
        stage: str,
        events: List[str],
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.stage = stage
        self.events = events
        self.result = result if result is not None else {"ok": True}
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def project_payload(self, **kwargs: Any) -> Dict[str, Any]:
        self.events.append(self.stage)
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return dict(self.result)

    async def clear_match(self, match_id: Any) -> Dict[str, Any]:
        self.events.append(self.stage + "_clear")
        return {"deleted": 0}


class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = list(docs)
        self._limit: Optional[int] = None

    def limit(self, value: int) -> "_FakeCursor":
        self._limit = value
        return self

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        effective = self._limit if self._limit is not None else length
        if effective is not None and effective > 0:
            return list(self._docs[:effective])
        return list(self._docs)


class _FakeMatchDetailCollection:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = list(docs)
        self.queries: List[Dict[str, Any]] = []

    def find(self, query: Dict[str, Any]) -> _FakeCursor:
        self.queries.append(dict(query))
        if not query:
            matched = list(self._docs)
        elif isinstance(query.get("match_id"), dict) and "$in" in query["match_id"]:
            allowed = set(query["match_id"]["$in"])
            matched = [doc for doc in self._docs if doc.get("match_id") in allowed]
        elif "match_id" in query:
            matched = [doc for doc in self._docs if doc.get("match_id") == query["match_id"]]
        else:
            matched = list(self._docs)
        return _FakeCursor(matched)


class _FakeDb:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self.jjc_match_detail = _FakeMatchDetailCollection(docs)


class TestJjcRankingStatsQuery(unittest.IsolatedAsyncioTestCase):
    def test_normalize_optional_text(self) -> None:
        self.assertIsNone(normalize_optional_text(None))
        self.assertIsNone(normalize_optional_text(""))
        self.assertIsNone(normalize_optional_text("   \t\n  "))
        self.assertEqual(normalize_optional_text("  abc  "), "abc")
        self.assertEqual(normalize_optional_text(12345), "12345")

    def test_build_peak_kungfu_statistics_three_lanes(self) -> None:
        items = [
            {"kungfu": "云裳心经", "score": 2500},
            {"kungfu": "补天诀", "score": 2400},
            {"kungfu": "冰心诀", "score": 2650},
            {"kungfu": "冰心诀", "score": 2550},
            {"kungfu": "铁牢律", "score": 2300},
            {"kungfu": "", "score": 2100},
            {"kungfu": "  ", "score": True},
            "not-a-dict",
        ]

        stats = build_peak_kungfu_statistics(items)  # type: ignore[arg-type]

        self.assertEqual(stats["healer"]["valid_count"], 2)
        self.assertEqual(stats["healer"]["min_score"], 2400)
        self.assertEqual(stats["healer"]["distribution"], {"云裳心经": 1, "补天诀": 1})

        self.assertEqual(stats["dps"]["valid_count"], 4)
        self.assertEqual(stats["dps"]["min_score"], 2100)
        self.assertEqual(stats["dps"]["distribution"], {"冰心诀": 2, "未知心法": 2})

        self.assertEqual(stats["tank"]["valid_count"], 1)
        self.assertEqual(stats["tank"]["min_score"], 2300)
        self.assertEqual(stats["tank"]["distribution"], {"铁牢律": 1})
        self.assertEqual(stats["tank"]["list"], [("铁牢律", 1)])
        self.assertEqual(stats["tank"]["legendary_count_map"], {})

    def test_build_peak_kungfu_statistics_empty_lane_min_score_dash(self) -> None:
        stats = build_peak_kungfu_statistics([{"kungfu": "离经易道", "score": 2450}])
        self.assertEqual(stats["healer"]["min_score"], 2450)
        self.assertEqual(stats["dps"]["min_score"], "-")
        self.assertEqual(stats["tank"]["min_score"], "-")

    async def test_load_peak_score_doc_invalid_range_returns_none(self) -> None:
        doc = await load_peak_score_doc(
            timestamp="1700000000",
            score_type="tuilan",
            range_key="top_999",
            version=1,
        )
        self.assertIsNone(doc)


class TestMatchDetailPersistenceStageIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_stage_failure_does_not_block_other_stages(self) -> None:
        events: List[str] = []
        identity = _FakeStageProjector("identity", events, result={"projected": 2})
        participant = _FakeStageProjector(
            "participant",
            events,
            error=RuntimeError("participant boom"),
        )
        fact = _FakeStageProjector("fact", events, result={"status": "updated"})

        service = MatchDetailPersistenceService(
            inspect_repo=_FakeInspectRepo(),
            identity_projector=identity,
            participant_projector=participant,
            fact_projector=fact,
        )
        payload = {"cached_at": 100, "data": {"match_id": 42, "detail": {}}}
        result = await service.persist(42, payload, "sync_worker")

        self.assertEqual(events, ["identity", "participant", "fact"])
        self.assertTrue(result.main_saved)
        self.assertTrue(result.identity_attempted)
        self.assertEqual(result.identity_result, {"projected": 2})
        self.assertIsNone(result.identity_error)
        self.assertTrue(result.participant_attempted)
        self.assertIsNone(result.participant_result)
        self.assertEqual(result.participant_error, "participant boom")
        self.assertTrue(result.fact_attempted)
        self.assertEqual(result.fact_result, {"status": "updated"})
        self.assertIsNone(result.fact_error)

    async def test_stage_returned_error_is_isolated(self) -> None:
        events: List[str] = []
        identity = _FakeStageProjector("identity", events, result={"error": "identity_err"})
        participant = _FakeStageProjector("participant", events, result={"projected": 6})
        fact = _FakeStageProjector("fact", events, result={"status": "inserted"})

        service = MatchDetailPersistenceService(
            inspect_repo=_FakeInspectRepo(),
            identity_projector=identity,
            participant_projector=participant,
            fact_projector=fact,
        )
        result = await service.persist(77, {"cached_at": 1, "data": {}}, "manual")

        self.assertEqual(events, ["identity", "participant", "fact"])
        self.assertEqual(result.identity_error, "identity_err")
        self.assertEqual(result.identity_result, {"error": "identity_err"})
        self.assertIsNone(result.participant_error)
        self.assertIsNone(result.fact_error)


class TestTuilanAuthErrorRecognition(unittest.TestCase):
    def test_recognizes_tuilan_auth_error_class(self) -> None:
        class TuilanAuthError(RuntimeError):
            pass

        self.assertTrue(is_tuilan_auth_error(TuilanAuthError("opaque_upstream_code")))
        self.assertFalse(is_tuilan_auth_error(RuntimeError("opaque_upstream_code")))
        self.assertTrue(is_tuilan_auth_error({"status_code": 401}))


class TestRebuildJjcProjectionsScript(unittest.IsolatedAsyncioTestCase):
    def test_parse_args_defaults_and_flags(self) -> None:
        defaults = rebuild_jjc_projections.parse_args([])
        self.assertEqual(defaults.stage, "all")
        self.assertIsNone(defaults.match_ids)
        self.assertEqual(defaults.limit, 0)
        self.assertFalse(defaults.dry_run)
        self.assertIsNone(defaults.mongo_uri)

        parsed = rebuild_jjc_projections.parse_args([
            "--stage", "fact",
            "--match-id", "101",
            "--match-id", "202",
            "--limit", "5",
            "--dry-run",
            "--mongo-uri", "mongodb://localhost:27017/custom_db",
        ])
        self.assertEqual(parsed.stage, "fact")
        self.assertEqual(parsed.match_ids, [101, 202])
        self.assertEqual(parsed.limit, 5)
        self.assertTrue(parsed.dry_run)
        self.assertEqual(parsed.mongo_uri, "mongodb://localhost:27017/custom_db")

    async def test_rebuild_projections_dry_run_counts_without_writing(self) -> None:
        docs = [
            {"match_id": 1001, "cached_at": 10, "data": {"detail": {}}},
            {"match_id": 1002, "cached_at": 20, "data": {"detail": {}}},
            {"match_id": -1, "cached_at": 30, "data": {"detail": {}}},
        ]
        db = _FakeDb(docs)
        events: List[str] = []
        fact = _FakeStageProjector("fact", events)
        participant = _FakeStageProjector("participant", events)
        identity = _FakeStageProjector("identity", events)

        summary = await rebuild_jjc_projections.rebuild_projections(
            db,
            stages=("fact", "participant", "identity"),
            dry_run=True,
            fact_projector=fact,
            participant_projector=participant,
            identity_projector=identity,
        )

        self.assertTrue(summary["dry_run"])
        self.assertEqual(summary["scanned"], 3)
        self.assertEqual(summary["skipped_invalid_match_id"], 1)
        self.assertEqual(events, [])
        for stage in ("fact", "participant", "identity"):
            self.assertEqual(summary["stage_stats"][stage]["would_process"], 2)
            self.assertEqual(summary["stage_stats"][stage]["processed"], 0)
            self.assertEqual(summary["stage_stats"][stage]["failed"], 0)

    async def test_rebuild_projections_selected_stage_and_match_ids(self) -> None:
        docs = [
            {"match_id": 1001, "cached_at": 10, "data": {"detail": {"a": 1}}},
            {"match_id": 1002, "cached_at": 20, "data": {"detail": {"a": 2}}},
            {"match_id": 1003, "cached_at": 30, "data": {"detail": {"a": 3}}},
        ]
        db = _FakeDb(docs)
        events: List[str] = []
        fact = _FakeStageProjector("fact", events)
        participant = _FakeStageProjector("participant", events)
        identity = _FakeStageProjector("identity", events)

        summary = await rebuild_jjc_projections.rebuild_projections(
            db,
            stages=("fact", "identity"),
            match_ids=[1001, 1003],
            dry_run=False,
            fact_projector=fact,
            participant_projector=participant,
            identity_projector=identity,
        )

        self.assertEqual(db.jjc_match_detail.queries, [{"match_id": {"$in": [1001, 1003]}}])
        self.assertEqual(summary["scanned"], 2)
        self.assertEqual(summary["stages"], ["fact", "identity"])
        self.assertEqual(summary["stage_stats"]["fact"]["processed"], 2)
        self.assertEqual(summary["stage_stats"]["identity"]["processed"], 2)
        self.assertNotIn("participant", summary["stage_stats"])
        self.assertEqual(len(fact.calls), 2)
        self.assertEqual(len(identity.calls), 2)
        self.assertEqual(len(participant.calls), 0)
        self.assertEqual(identity.calls[0]["payload"], {"detail": {"a": 1}})


if __name__ == "__main__":
    unittest.main()
