"""Tests for the read-only JJC matchup explain and capacity CLI."""

import argparse
import asyncio
import copy
import importlib.util
import json
import sys
import time
import unittest
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from pymongo.errors import ConfigurationError


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_jjc_matchup_performance.py"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("check_jjc_matchup_performance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "mongo_uri": None,
        "db_name": None,
        "end_time": 1_700_000_000,
        "score_min": 0,
        "score_max": 1_000_000,
        "sample_size": 4,
        "batch_size": 50,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class _AsyncItems:
    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self.items = items

    def __aiter__(self) -> "_AsyncItems":
        self._index = 0
        return self

    async def __anext__(self) -> Dict[str, Any]:
        if self._index >= len(self.items):
            raise StopAsyncIteration
        result = self.items[self._index]
        self._index += 1
        return result


class _CaptureCollection:
    def __init__(self) -> None:
        self.pipelines: List[List[Dict[str, Any]]] = []

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> _AsyncItems:
        self.pipelines.append(pipeline)
        return _AsyncItems([{"missing": [], "statistics": [], "total": [], "items": []}])


class _CapacityCollection:
    def __init__(
        self,
        active_count: int = 0,
        tombstone_count: int = 0,
        active_samples: Optional[List[Dict[str, Any]]] = None,
        tombstone_samples: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.counts = {True: active_count, False: tombstone_count}
        self.samples = {True: active_samples or [], False: tombstone_samples or []}
        self.aggregates: List[Dict[str, Any]] = []

    async def count_documents(self, query: Dict[str, Any]) -> int:
        return self.counts[query["active"]]

    def aggregate(self, pipeline: List[Dict[str, Any]], **kwargs: Any) -> _AsyncItems:
        self.aggregates.append({"pipeline": pipeline, "kwargs": kwargs})
        return _AsyncItems(self.samples[pipeline[0]["$match"]["active"]])


class _HistoricalDetailCollection:
    def __init__(self, count: int, samples: List[Dict[str, Any]]) -> None:
        self.count = count
        self.samples = samples
        self.aggregates: List[Dict[str, Any]] = []

    async def count_documents(self, query: Dict[str, Any]) -> int:
        self.query = query
        return self.count

    def aggregate(self, pipeline: List[Dict[str, Any]], **kwargs: Any) -> _AsyncItems:
        self.aggregates.append({"pipeline": pipeline, "kwargs": kwargs})
        projection = next((stage["$project"] for stage in pipeline if "$project" in stage), {})
        return _AsyncItems([self._project(document, projection) for document in self.samples])

    @classmethod
    def _project(cls, document: Dict[str, Any], projection: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for field, included in projection.items():
            if included and field != "_id":
                cls._merge(result, cls._select(document, field.split(".")))
        return result

    @classmethod
    def _select(cls, value: Any, parts: List[str]) -> Any:
        if not parts:
            return copy.deepcopy(value)
        if isinstance(value, dict) and parts[0] in value:
            return {parts[0]: cls._select(value[parts[0]], parts[1:])}
        if isinstance(value, list):
            return [cls._select(item, parts) for item in value]
        return {}

    @classmethod
    def _merge(cls, target: Any, source: Any) -> Any:
        if isinstance(target, dict) and isinstance(source, dict):
            for key, value in source.items():
                if key in target:
                    cls._merge(target[key], value)
                else:
                    target[key] = value
        elif isinstance(target, list) and isinstance(source, list):
            for index, value in enumerate(source):
                if index < len(target):
                    cls._merge(target[index], value)
                else:
                    target.append(value)
        return target


class _Database:
    def __init__(self, explain: Optional[Dict[str, Any]] = None) -> None:
        self.jjc_match_facts = _CapacityCollection()
        self.jjc_match_detail = _HistoricalDetailCollection(0, [])
        self.commands: List[Dict[str, Any]] = []
        self.explain = explain or {"executionStats": {"totalKeysExamined": 0, "totalDocsExamined": 0, "executionTimeMillis": 0}}

    async def command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        self.commands.append(command)
        return self.explain

    def __bool__(self) -> bool:
        raise AssertionError("Motor Database must never be tested for truthiness")


class _Client:
    def __init__(self, database: _Database, default_error: bool = False) -> None:
        self.database = database
        self.default_error = default_error
        self.closed = False
        self.requested_names: List[str] = []

    def get_default_database(self, default: Any = None) -> Any:
        if self.default_error:
            raise ConfigurationError("No default database name defined")
        return None

    def __getitem__(self, name: str) -> _Database:
        self.requested_names.append(name)
        return self.database

    def close(self) -> None:
        self.closed = True


class CheckJjcMatchupPerformanceTests(unittest.TestCase):
    def test_capture_reuses_repo_pipeline_for_all_shapes_and_windows(self) -> None:
        module = _load_script()
        calls: List[Dict[str, Any]] = []
        original = module.JjcMatchFactRepo.search_matchups

        async def recording(repo: Any, filters: Dict[str, Any]) -> Dict[str, Any]:
            calls.append(dict(filters))
            return await original(repo, filters)

        module.JjcMatchFactRepo.search_matchups = recording
        try:
            cases = module.build_cases(_args())
            self.assertEqual(len(cases), 10)
            for case in cases:
                pipeline = asyncio.run(module.capture_search_pipeline(case["filters"]))
                self.assertTrue(pipeline)
                self.assertEqual(pipeline[0]["$match"]["active"], True)
                self.assertEqual(pipeline[1], {"$sort": {"match_time": -1, "match_id": -1}})
        finally:
            module.JjcMatchFactRepo.search_matchups = original

        self.assertEqual(len(calls), 10)
        self.assertEqual({case["name"] for case in cases}, {
            "single_kungfu", "double_kungfu", "full_combo", "one_side_empty", "both_sides_empty",
        })
        self.assertEqual({case["window_days"] for case in cases}, {7, 14})
        expected_teams = {
            "single_kungfu": ([10080], [10242]),
            "double_kungfu": ([10080, 10242], [10081, 10243]),
            "full_combo": ([10080, 10242, 10390], [10081, 10243, 10391]),
            "one_side_empty": ([], [10080, 10242]),
            "both_sides_empty": ([], []),
        }
        for case in cases:
            filters = case["filters"]
            self.assertEqual(filters["page"], 1)
            self.assertEqual(filters["page_size"], 20)
            self.assertLess(filters["score_min"], filters["score_max"])
            self.assertEqual(filters["end_time"] - filters["start_time"], case["window_days"] * 86400)
            self.assertEqual(
                (filters["team_a_kungfu_ids"], filters["team_b_kungfu_ids"]),
                expected_teams[case["name"]],
            )

    def test_collect_report_uses_ten_execution_stats_explains_and_parses_metrics(self) -> None:
        module = _load_script()
        explain = {
            "executionStats": {"totalKeysExamined": 12, "totalDocsExamined": 8, "executionTimeMillis": 17},
            "queryPlanner": {"winningPlan": {"stage": "FETCH", "inputStage": {"stage": "IXSCAN", "indexName": "idx_active_combo_time", "keyPattern": {"match_time": -1}}}},
            "stages": [{"$facet": {"errorMessage": "Exceeded memory limit of 100MB"}}],
        }
        database = _Database(explain)

        report = asyncio.run(module.collect_report(_args(), database))

        self.assertEqual(len(database.commands), 10)
        for command in database.commands:
            self.assertEqual(command["verbosity"], "executionStats")
            self.assertEqual(command["explain"]["aggregate"], "jjc_match_facts")
            self.assertIn("pipeline", command["explain"])
        case = report["performance"][0]
        self.assertEqual(case["index_names"], ["idx_active_combo_time"])
        self.assertFalse(case["blocking_sort"])
        self.assertEqual(case["keys_examined"], 12)
        self.assertEqual(case["docs_examined"], 8)
        self.assertEqual(case["execution_time_ms"], 17)
        self.assertEqual(case["facet_errors"], ["Exceeded memory limit of 100MB"])
        self.assertNotIn("mongo_uri", json.dumps(report))

    def test_collect_report_isolates_one_failed_explain_and_continues(self) -> None:
        module = _load_script()
        database = _Database()

        class ExplainError(RuntimeError):
            code = 9
            name = "ExplainDenied"

        original_command = database.command

        async def fail_once(command: Dict[str, Any]) -> Dict[str, Any]:
            if not database.commands:
                database.commands.append(command)
                raise ExplainError("connection details must not be reported")
            return await original_command(command)

        database.command = fail_once
        report = asyncio.run(module.collect_report(_args(), database))

        self.assertEqual(len(report["performance"]), 10)
        self.assertEqual(report["failed_case_count"], 1)
        failed = report["performance"][0]
        self.assertEqual(failed["name"], "single_kungfu")
        self.assertEqual(failed["window_days"], 7)
        self.assertEqual(failed["index_names"], [])
        self.assertFalse(failed["blocking_sort"])
        self.assertEqual((failed["keys_examined"], failed["docs_examined"], failed["execution_time_ms"]), (0, 0, 0))
        self.assertEqual(failed["facet_errors"], [{"error_type": "ExplainError", "code": 9, "name": "ExplainDenied"}])
        self.assertNotIn("connection details", json.dumps(report))
        self.assertEqual(len(database.commands), 10)

    def test_parse_explain_distinguishes_real_sort_stage_from_index_direction(self) -> None:
        module = _load_script()
        only_index_direction = {
            "queryPlanner": {"winningPlan": {"stage": "IXSCAN", "indexName": "idx_active_time", "keyPattern": {"match_time": -1}}},
            "executionStats": {"totalKeysExamined": 3, "totalDocsExamined": 2, "executionTimeMillis": 1},
        }
        real_sort = {"queryPlanner": {"winningPlan": {"stage": "SORT", "inputStage": {"stage": "IXSCAN", "indexName": "idx_active_time"}}}}
        parsed = module.parse_explain(only_index_direction)
        self.assertEqual(parsed["index_names"], ["idx_active_time"])
        self.assertFalse(parsed["blocking_sort"])
        self.assertTrue(module.parse_explain(real_sort)["blocking_sort"])

    def test_parse_explain_ignores_sort_in_rejected_plans(self) -> None:
        module = _load_script()
        parsed = module.parse_explain({
            "queryPlanner": {
                "winningPlan": {"stage": "IXSCAN", "indexName": "idx_active_time"},
                "rejectedPlans": [{"stage": "SORT", "inputStage": {"stage": "COLLSCAN"}}],
            },
        })
        self.assertFalse(parsed["blocking_sort"])

    def test_parse_explain_reads_cursor_stats_and_sort_from_each_shard(self) -> None:
        module = _load_script()
        parsed = module.parse_explain({
            "shards": {
                "first": {"stages": [{"$cursor": {
                    "queryPlanner": {"winningPlan": {"stage": "IXSCAN", "indexName": "idx_active_time"}},
                    "executionStats": {
                        "totalKeysExamined": 2, "totalDocsExamined": 3, "executionTimeMillis": 4,
                        "executionStages": {"stage": "FETCH", "inputStage": {"stage": "IXSCAN"}},
                    },
                }}]},
                "second": {"stages": [{"$cursor": {
                    "queryPlanner": {"winningPlan": {"stage": "SORT", "inputStage": {"stage": "IXSCAN"}}},
                    "executionStats": {
                        "totalKeysExamined": 5, "totalDocsExamined": 7, "executionTimeMillis": 11,
                        "executionStages": {"stage": "SORT", "inputStage": {"stage": "IXSCAN"}},
                    },
                }}]},
            },
        })
        self.assertEqual((parsed["keys_examined"], parsed["docs_examined"], parsed["execution_time_ms"]), (7, 10, 15))
        self.assertTrue(parsed["blocking_sort"])

    def test_parse_explain_reads_only_selected_index_and_sort_from_root_cursor(self) -> None:
        module = _load_script()
        parsed = module.parse_explain({
            "stages": [{"$cursor": {
                "queryPlanner": {
                    "winningPlan": {"stage": "SORT", "inputStage": {"stage": "IXSCAN", "indexName": "idx_used"}},
                    "rejectedPlans": [{"stage": "IXSCAN", "indexName": "idx_rejected"}],
                },
                "executionStats": {"executionStages": {"stage": "SORT", "inputStage": {"stage": "IXSCAN", "indexName": "idx_used"}}},
            }}],
        })
        self.assertTrue(parsed["blocking_sort"])
        self.assertEqual(parsed["index_names"], ["idx_used"])

    def test_parse_explain_recurses_execution_and_execution_failure(self) -> None:
        module = _load_script()
        parsed = module.parse_explain({
            "shards": [{"executionStats": {
                "totalKeysExamined": 7, "totalDocsExamined": 5, "executionTimeMillis": 4,
            }}],
            "stages": [{"$facet": {"executionFailure": True}}],
        })
        self.assertEqual(parsed["keys_examined"], 7)
        self.assertEqual(parsed["docs_examined"], 5)
        self.assertEqual(parsed["execution_time_ms"], 4)
        self.assertEqual(parsed["facet_errors"], ["executionFailure"])

    def test_parse_explain_prefers_root_totals_over_nested_execution_stats(self) -> None:
        module = _load_script()
        parsed = module.parse_explain({
            "executionStats": {"totalKeysExamined": 11, "totalDocsExamined": 12, "executionTimeMillis": 13},
            "executionStages": {"executionStats": {"totalKeysExamined": 101, "totalDocsExamined": 102, "executionTimeMillis": 103}},
        })
        self.assertEqual((parsed["keys_examined"], parsed["docs_examined"], parsed["execution_time_ms"]), (11, 12, 13))

    def test_parse_explain_sums_only_top_execution_stats_per_shard(self) -> None:
        module = _load_script()
        parsed = module.parse_explain({
            "shards": {
                "first": {
                    "executionStats": {"totalKeysExamined": 2, "totalDocsExamined": 3, "executionTimeMillis": 4},
                    "executionStages": {"executionStats": {"totalKeysExamined": 200, "totalDocsExamined": 300, "executionTimeMillis": 400}},
                },
                "second": {
                    "executionStats": {"totalKeysExamined": 5, "totalDocsExamined": 7, "executionTimeMillis": 11},
                    "nested": {"executionStats": {"totalKeysExamined": 500, "totalDocsExamined": 700, "executionTimeMillis": 1100}},
                },
            },
        })
        self.assertEqual((parsed["keys_examined"], parsed["docs_examined"], parsed["execution_time_ms"]), (7, 10, 15))

    def test_capacity_handles_empty_active_and_tombstone_samples_as_zero(self) -> None:
        module = _load_script()
        database = _Database()
        database.jjc_match_facts = _CapacityCollection(0, 0, [], [])
        capacity = asyncio.run(module.collect_capacity(database, sample_size=3, batch_size=4))
        for key, value in capacity.items():
            if key.endswith("documents") or key.endswith("sample_count") or "bson" in key or "combo" in key:
                self.assertEqual(value, 0, key)

    def test_capacity_uses_history_samples_when_facts_are_empty(self) -> None:
        module = _load_script()
        database = _Database()
        database.jjc_match_facts = _CapacityCollection()
        samples = [
            {"match_id": 1, "cached_at": 10, "data": {"kind": "complete"}},
            {"match_id": 2, "cached_at": 20, "data": {"kind": "incomplete"}},
            {"match_id": 3, "cached_at": 30, "data": {"kind": "unavailable"}},
            {"match_id": 4, "cached_at": 40, "data": {"kind": "invalid"}},
        ]
        database.jjc_match_detail = _HistoricalDetailCollection(20, samples)

        def build(match_id: int, payload: Dict[str, Any], schema: int) -> Dict[str, Any]:
            kind = {1: "complete", 2: "incomplete", 3: "unavailable", 4: "invalid"}[match_id]
            if kind in ("complete", "incomplete"):
                return {
                    "match_id": match_id,
                    "active": True,
                    "any_team_combo_keys": ["a"] if kind == "complete" else ["a", "b"],
                    "team1": {"score_complete": kind == "complete"},
                    "team2": {"score_complete": kind == "complete"},
                }
            return {"match_id": match_id, "active": False, "invalid_reason": kind}

        capacity = asyncio.run(module.collect_capacity(
            database, sample_size=4, batch_size=7, fact_builder=build,
        ))

        active_facts = [build(1, samples[0], 1), build(2, samples[1], 1)]
        tombstone_facts = [build(3, samples[2], 1), build(4, samples[3], 1)]
        self.assertEqual(capacity["source_documents"], 20)
        self.assertEqual(capacity["source_sample_count"], 4)
        self.assertEqual(capacity["active_sample_count"], 2)
        self.assertEqual(capacity["score_incomplete_active_sample_count"], 1)
        self.assertEqual(capacity["score_incomplete_active_estimated_documents"], 5.0)
        self.assertEqual(capacity["tombstone_sample_count"], 2)
        self.assertEqual(capacity["active_estimated_documents"], 10.0)
        self.assertEqual(capacity["tombstone_estimated_documents"], 10.0)
        self.assertEqual(
            capacity["active_average_bson_bytes"],
            sum(len(module.BSON.encode(fact)) for fact in active_facts) / 2,
        )
        self.assertEqual(
            capacity["tombstone_average_bson_bytes"],
            sum(len(module.BSON.encode(fact)) for fact in tombstone_facts) / 2,
        )
        self.assertEqual(capacity["active_average_combo_index_entries"], 1.5)
        self.assertEqual(capacity["active_estimated_combo_index_entries"], 15.0)
        aggregate = database.jjc_match_detail.aggregates[0]
        self.assertEqual(aggregate["kwargs"], {"batchSize": 7})
        self.assertEqual(aggregate["pipeline"][0], {"$sample": {"size": 4}})
        projection = aggregate["pipeline"][1]["$project"]
        for forbidden in ("equipment", "qixue", "replay", "metrics"):
            self.assertFalse(any(forbidden in field for field in projection), forbidden)
        self.assertIn("data.team1.players_info.kungfu_id", projection)
        self.assertIn("data.detail.team2.players.score", projection)

    def test_capacity_counts_invalid_ids_and_build_failures_without_classifying_them(self) -> None:
        module = _load_script()
        database = _Database()
        database.jjc_match_detail = _HistoricalDetailCollection(10, [
            {"match_id": "bad", "cached_at": 1, "data": {}},
            {"match_id": 2, "cached_at": 1, "data": {"fail": True}},
            {"match_id": 3, "cached_at": 1, "data": {}},
        ])

        def build(match_id: int, payload: Dict[str, Any], schema: int) -> Dict[str, Any]:
            if match_id == 2:
                raise ValueError("cannot build")
            return {"match_id": match_id, "active": True, "any_team_combo_keys": []}

        capacity = asyncio.run(module.collect_capacity(
            database, sample_size=3, batch_size=2, fact_builder=build,
        ))

        self.assertEqual(capacity["source_sample_count"], 3)
        self.assertEqual(capacity["invalid_match_id"], 1)
        self.assertEqual(capacity["build_failed"], 1)
        self.assertEqual(capacity["active_sample_count"], 1)
        self.assertEqual(capacity["tombstone_sample_count"], 0)

    def test_capacity_default_builder_classifies_real_projected_detail_facts(self) -> None:
        module = _load_script()
        database = _Database()

        def player(kungfu_id: int, score: Any) -> Dict[str, Any]:
            return {
                "role_name": "role{}".format(kungfu_id), "server": "server",
                "kungfu_id": kungfu_id, "kungfu": "kungfu{}".format(kungfu_id),
                "total_score": score, "score": score,
                "equipment": {"large": True}, "metrics": ["large"],
            }

        def detail_document(match_id: int, team1: List[Dict[str, Any]], team2: List[Dict[str, Any]]) -> Dict[str, Any]:
            return {
                "match_id": match_id, "cached_at": 100,
                "data": {"detail": {
                    "match_time": 99,
                    "basic_info": {"match_type": 3, "map": "map", "duration": 1},
                    "team1": {"won": True, "players_info": team1},
                    "team2": {"won": False, "players_info": team2},
                    "replay": {"large": True},
                }},
            }

        complete_a = [player(10001, 1000), player(10002, 1000), player(10003, 1000)]
        complete_b = [player(10004, 1000), player(10005, 1000), player(10006, 1000)]
        incomplete_a = [player(10007, None), player(10008, 1000), player(10009, 1000)]
        database.jjc_match_detail = _HistoricalDetailCollection(4, [
            detail_document(1, complete_a, complete_b),
            detail_document(2, incomplete_a, complete_b),
            {"match_id": 3, "cached_at": 100, "data": {"unavailable": True}},
            detail_document(4, complete_a[:2], complete_b),
        ])

        capacity = asyncio.run(module.collect_capacity(database, sample_size=4, batch_size=3))

        self.assertEqual(capacity["active_sample_count"], 2)
        self.assertEqual(capacity["tombstone_sample_count"], 2)
        self.assertEqual(capacity["score_incomplete_active_sample_count"], 1)

    def test_score_bounds_are_loaded_from_matchup_service_meta_contract(self) -> None:
        module = _load_script()

        class FakeMatchupService:
            def __init__(self, repo: Any) -> None:
                self.repo = repo

            def get_meta(self) -> Dict[str, Any]:
                return {"limits": {"score_min": 7, "score_max": 99}}

        with patch.object(module, "JjcMatchupService", FakeMatchupService):
            self.assertEqual(module._load_score_limits(), {"score_min": 7, "score_max": 99})
        self.assertEqual(module.SCORE_LIMITS, module._load_score_limits())

    def test_validation_rejects_non_positive_and_invalid_score_flags(self) -> None:
        module = _load_script()
        for field in ("end_time", "sample_size", "batch_size"):
            with self.assertRaisesRegex(ValueError, field.replace("_", "-")):
                module.validate_args(_args(**{field: 0}))
        with self.assertRaisesRegex(ValueError, "score-min"):
            module.validate_args(_args(score_min=-1))
        with self.assertRaisesRegex(ValueError, "score-max"):
            module.validate_args(_args(score_min=10, score_max=10))
        valid = _args()
        self.assertIs(module.validate_args(valid), valid)

    def test_parser_defaults_end_time_to_the_current_runtime_time(self) -> None:
        module = _load_script()
        before = int(time.time())
        args = module.parse_args([])
        after = int(time.time())
        self.assertGreaterEqual(args.end_time, before)
        self.assertLessEqual(args.end_time, after)

    def test_run_falls_back_after_configuration_error_and_always_closes_client(self) -> None:
        module = _load_script()
        database = _Database()
        client = _Client(database, default_error=True)
        result = asyncio.run(module.run(_args(mongo_uri="mongodb://example.invalid"), client_factory=lambda *a, **k: client))
        self.assertEqual(len(result["performance"]), 10)
        self.assertEqual(client.requested_names, ["jx3bot"])
        self.assertTrue(client.closed)

    def test_run_isolates_explain_errors_and_closes_client(self) -> None:
        module = _load_script()
        database = _Database()
        client = _Client(database)

        async def fail(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("connection broken")

        database.command = fail
        report = asyncio.run(module.run(
            _args(mongo_uri="mongodb://example.invalid", db_name="jjc"),
            client_factory=lambda *a, **k: client,
        ))
        self.assertEqual(report["failed_case_count"], 10)
        self.assertTrue(client.closed)

    def test_main_emits_one_json_on_stdout_or_a_nonzero_stderr_error(self) -> None:
        module = _load_script()

        async def report(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            return {"performance": [], "capacity": {}}

        stdout, stderr = StringIO(), StringIO()
        with patch.object(module, "run", report), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            self.assertEqual(module.main([]), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"performance": [], "capacity": {}})
        self.assertEqual(stderr.getvalue(), "")

        async def fail(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("database connection failed")

        stdout, stderr = StringIO(), StringIO()
        with patch.object(module, "run", fail), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            self.assertEqual(module.main([]), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue()), {"error_type": "RuntimeError"})

    def test_no_hardcoded_credentials_in_script_source(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""
        self.assertNotRegex(source, r"mongodb(?:\+srv)?://[^\s\"']+:[^\s\"']+@")
