"""Contracts for the safe JJC match-fact backfill command."""

import argparse
import asyncio
import importlib.util
import unittest
from pathlib import Path
from typing import Any, Dict, List

from pymongo.errors import ConfigurationError


SCRIPT_PATH = Path("scripts/backfill_jjc_match_facts.py")


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("backfill_jjc_match_facts_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load backfill script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "mongo_uri": None,
        "db_name": None,
        "resume_after_match_id": None,
        "batch_size": 2,
        "limit": 0,
        "dry_run": False,
        "apply": False,
        "yes": False,
        "verify_only": False,
        "missing_only": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _fact(match_id: int, active: bool = True, complete: bool = True) -> Dict[str, Any]:
    fact = {
        "match_id": match_id,
        "active": active,
        "source_hash": "a" * 64,
        "schema_version": 1,
        "source_cached_at": 100.0,
    }
    if active:
        fact.update({
            "match_time": 100,
            "map": "map",
            "duration": 60,
            "match_type": 3,
            "team1": {"score_complete": complete},
            "team2": {"score_complete": complete},
            "any_team_combo_keys": [],
            "min_team_score_sum": 0,
            "max_team_score_sum": 0,
        })
    else:
        fact["invalid_reason"] = "invalid_team_structure"
    return fact


class _RecordingRepo:
    def __init__(self, statuses: List[str], states: Dict[int, Dict[str, Any]] = None, events: List[Any] = None) -> None:
        self.statuses = list(statuses)
        self.applied: List[Dict[str, Any]] = []
        self.states = states or {}
        self.events = events
        self.state_batches: List[List[int]] = []

    async def apply_projection(self, fact: Dict[str, Any]) -> str:
        self.applied.append(fact)
        if self.events is not None:
            self.events.append(("apply", fact["match_id"]))
        return self.statuses.pop(0)

    async def get_projection_state(self, match_id: int) -> Dict[str, Any]:
        return self.states.get(match_id)

    async def get_projection_states(self, match_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        self.state_batches.append(list(match_ids))
        return {match_id: self.states[match_id] for match_id in match_ids if match_id in self.states}


class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]], events: List[Any] = None) -> None:
        self.docs = docs
        self.events = events
        self.sorted = None
        self.batch_size_value = None

    def sort(self, *args: Any) -> "_FakeCursor":
        self.sorted = args
        return self

    def batch_size(self, value: int) -> "_FakeCursor":
        self.batch_size_value = value
        return self

    def __aiter__(self) -> Any:
        async def generate() -> Any:
            for doc in self.docs:
                if self.events is not None:
                    self.events.append(("yield", doc["match_id"]))
                yield doc
        return generate()


class _FakeCollection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.cursor = cursor
        self.find_calls: List[Any] = []

    def find(self, *args: Any, **kwargs: Any) -> _FakeCursor:
        self.find_calls.append((args, kwargs))
        return self.cursor


class _QueryRecordingCollection:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self.docs = docs
        self.find_calls: List[Any] = []
        self.cursors: List[_FakeCursor] = []

    def find(self, query: Dict[str, Any], projection: Dict[str, Any], **kwargs: Any) -> _FakeCursor:
        self.find_calls.append((query, projection))
        match_ids = query.get("match_id", {}).get("$in")
        if match_ids is None:
            cursor = _FakeCursor(list(self.docs))
        else:
            cursor = _FakeCursor([doc for doc in self.docs if doc.get("match_id") in match_ids])
        self.cursors.append(cursor)
        return cursor


class _OrphanCheckDb:
    def __init__(self, source_docs: List[Dict[str, Any]], fact_docs: List[Dict[str, Any]]) -> None:
        self.jjc_match_detail = _QueryRecordingCollection(source_docs)
        self.jjc_match_facts = _QueryRecordingCollection(fact_docs)


class _FakeDb:
    def __init__(self, cursor: _FakeCursor, fact_cursor: _FakeCursor = None) -> None:
        self.jjc_match_detail = _FakeCollection(cursor)
        self.jjc_match_facts = _FakeCollection(fact_cursor or _FakeCursor([]))


class _FakeClient:
    def __init__(self, db: _FakeDb, default_db: Any = None) -> None:
        self.db = db
        self.default_db = default_db
        self.closed = False
        self.selected_name = None

    def __getitem__(self, name: str) -> _FakeDb:
        self.selected_name = name
        return self.db

    def get_default_database(self, default: Any = None) -> Any:
        return self.default_db if self.default_db is not None else default

    def close(self) -> None:
        self.closed = True


class TestBackfillJjcMatchFacts(unittest.TestCase):
    def test_default_mode_is_dry_run_and_writes_require_apply_yes(self) -> None:
        module = _load_script()

        args = module.validate_args(_args())
        self.assertTrue(args.dry_run)
        with self.assertRaisesRegex(ValueError, "--apply requires --yes"):
            module.validate_args(_args(apply=True))
        self.assertFalse(module.validate_args(_args(apply=True, yes=True)).dry_run)
        with self.assertRaisesRegex(ValueError, "verify-only"):
            module.validate_args(_args(apply=True, yes=True, verify_only=True))

    def test_validates_positive_resume_batch_size_and_limit(self) -> None:
        module = _load_script()

        with self.assertRaisesRegex(ValueError, "resume-after-match-id"):
            module.validate_args(_args(resume_after_match_id=0))
        with self.assertRaisesRegex(ValueError, "batch-size"):
            module.validate_args(_args(batch_size=0))
        with self.assertRaisesRegex(ValueError, "limit"):
            module.validate_args(_args(limit=-1))
        args = module.validate_args(_args(resume_after_match_id=9, batch_size=3, limit=4))
        self.assertEqual(module.build_query(args), {"match_id": {"$gt": 9}})

    def test_source_payload_preserves_all_root_actual_time_aliases(self) -> None:
        module = _load_script()
        document = {
            "cached_at": 10,
            "data": {"detail": {}},
            "match_time": 11,
            "matchTime": 12,
            "start_time": 13,
            "startTime": 14,
            "time": 15,
        }

        payload = module._source_payload(document)

        self.assertEqual(payload["data"], {"detail": {}})
        for key, value in document.items():
            if key not in ("cached_at", "data"):
                self.assertEqual(payload[key], value)

    def test_dry_run_classifies_active_tombstone_and_incomplete_without_writing(self) -> None:
        module = _load_script()
        repo = _RecordingRepo([])
        docs = [{"match_id": 1}, {"match_id": 2}, {"match_id": 3}]
        facts = [_fact(1), _fact(2, complete=False), _fact(3, active=False)]

        stats = asyncio.run(module.process_batch(
            repo=repo,
            docs=docs,
            dry_run=True,
            verify_only=False,
            fact_builder=lambda match_id, payload, schema: facts[match_id - 1],
        ))

        self.assertEqual(repo.applied, [])
        self.assertEqual(stats["active"], 2)
        self.assertEqual(stats["inactive"], 1)
        self.assertEqual(stats["structural_skipped"], 1)
        self.assertEqual(stats["score_incomplete"], 1)
        self.assertEqual(stats["would_apply"], 3)
        self.assertEqual(stats["last_successful_match_id"], 3)

    def test_dry_run_predicts_cas_statuses_without_writing(self) -> None:
        module = _load_script()
        repo = _RecordingRepo([], states={
            2: dict(_fact(2), source_cached_at=200.0),
            3: dict(_fact(3), source_hash="b" * 64),
            4: _fact(4),
            5: dict(_fact(5), schema_version=0),
        })
        docs = [{"match_id": match_id} for match_id in range(1, 7)]

        def build(match_id: int, payload: Dict[str, Any], schema: int) -> Dict[str, Any]:
            return _fact(match_id, active=match_id != 6)

        stats = asyncio.run(module.process_batch(
            repo=repo, docs=docs, dry_run=True, verify_only=False, fact_builder=build,
        ))

        self.assertEqual(repo.applied, [])
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["skipped_old"], 1)
        self.assertEqual(stats["conflict"], 1)
        self.assertEqual(stats["last_successful_match_id"], 2)
        self.assertEqual(repo.state_batches, [[1, 2, 3, 4, 5, 6]])

    def test_dry_run_invalid_projection_counts_failure_without_advancing_watermark(self) -> None:
        module = _load_script()
        module._log = lambda message: None
        stats = asyncio.run(module.process_batch(
            repo=_RecordingRepo([]), docs=[{"match_id": 1}], dry_run=True, verify_only=False,
            fact_builder=lambda match_id, payload, schema: dict(_fact(match_id), source_cached_at=None),
        ))
        self.assertEqual(stats["apply_failed"], 1)
        self.assertEqual(stats["last_successful_match_id"], 0)

    def test_batch_failures_log_match_id_stage_and_error_type(self) -> None:
        module = _load_script()
        messages: List[str] = []
        module._log = messages.append

        asyncio.run(module.process_batch(
            repo=_RecordingRepo([]), docs=[{"match_id": 1}], dry_run=False, verify_only=False,
            fact_builder=lambda match_id, payload, schema: (_ for _ in ()).throw(ValueError("bad source")),
        ))

        self.assertEqual(messages, ["[FAIL] match_id=1 stage=build error_type=ValueError"])

    def test_apply_failure_logs_match_id_stage_and_error_type(self) -> None:
        module = _load_script()
        messages: List[str] = []
        module._log = messages.append

        class FailingRepo(_RecordingRepo):
            async def apply_projection(self, fact: Dict[str, Any]) -> str:
                raise RuntimeError("database unavailable")

        asyncio.run(module.process_batch(
            repo=FailingRepo([]), docs=[{"match_id": 1}], dry_run=False, verify_only=False,
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
        ))

        self.assertEqual(messages, ["[FAIL] match_id=1 stage=apply error_type=RuntimeError"])

    def test_dry_run_state_lookup_failure_logs_batch_stage_and_error_type(self) -> None:
        module = _load_script()
        messages: List[str] = []
        module._log = messages.append

        class FailingRepo(_RecordingRepo):
            async def get_projection_states(self, match_ids: List[int]) -> Dict[int, Dict[str, Any]]:
                raise RuntimeError("database unavailable")

        asyncio.run(module.process_batch(
            repo=FailingRepo([]), docs=[{"match_id": 1}, {"match_id": 2}], dry_run=True, verify_only=False,
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
        ))

        self.assertEqual(messages, ["[FAIL] match_ids=1,2 stage=dry_run_states error_type=RuntimeError"])

    def test_apply_stops_at_conflict_without_advancing_safe_watermark(self) -> None:
        module = _load_script()
        repo = _RecordingRepo(["inserted", "updated", "tombstoned", "skipped_old", "conflict", "noop"])
        docs = [{"match_id": match_id} for match_id in range(1, 7)]

        def build(match_id: int, payload: Dict[str, Any], schema: int) -> Dict[str, Any]:
            return _fact(match_id, active=match_id == 3 and False or True)

        stats = asyncio.run(module.process_batch(
            repo=repo, docs=docs, dry_run=False, verify_only=False, fact_builder=build,
        ))

        for status in ("inserted", "updated", "tombstoned", "skipped_old", "conflict"):
            self.assertEqual(stats[status], 1)
        self.assertEqual(stats["noop"], 0)
        self.assertEqual(stats["build_failed"], 0)
        self.assertEqual(stats["last_successful_match_id"], 4)
        self.assertEqual(stats["blocking_failure"], 1)

    def test_verify_reports_all_projection_consistency_categories(self) -> None:
        module = _load_script()
        docs = [{"match_id": match_id} for match_id in range(1, 6)]
        repo = _RecordingRepo([], states={
            1: _fact(1),
            2: _fact(2),
            3: dict(_fact(3), source_hash="b" * 64),
            4: dict(_fact(4), schema_version=0),
            99: _fact(99),
        })

        def build(match_id: int, payload: Dict[str, Any], schema: int) -> Dict[str, Any]:
            if match_id == 5:
                raise ValueError("cannot build")
            return _fact(match_id, active=match_id != 2)

        stats = asyncio.run(module.verify_batch(
            repo=repo,
            docs=docs,
            fact_builder=build,
            projection_states=repo.states,
        ))

        self.assertEqual(stats["missing"], 1)
        self.assertEqual(stats["orphan"], 1)
        self.assertEqual(stats["should_be_inactive"], 1)
        self.assertEqual(stats["hash_mismatch"], 1)
        self.assertEqual(stats["schema_outdated"], 1)
        self.assertEqual(stats["build_failed"], 1)

    def test_verify_reports_missing_or_invalid_schema_versions(self) -> None:
        module = _load_script()

        for schema_version in (None, "1", False, 0):
            with self.subTest(schema_version=schema_version):
                current = _fact(1)
                if schema_version is None:
                    current.pop("schema_version")
                else:
                    current["schema_version"] = schema_version
                stats = asyncio.run(module.verify_batch(
                    repo=None,
                    docs=[{"match_id": 1}],
                    fact_builder=lambda match_id, payload, schema: _fact(match_id),
                    projection_states={1: current},
                ))
                self.assertEqual(stats["schema_outdated"], 1)

    def test_verify_does_not_report_a_higher_schema_version_as_outdated(self) -> None:
        module = _load_script()
        stats = asyncio.run(module.verify_batch(
            repo=None,
            docs=[{"match_id": 1}],
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
            projection_states={1: dict(_fact(1), schema_version=2)},
        ))

        self.assertEqual(stats["schema_outdated"], 0)

    def test_scoped_verify_skips_global_orphan_check(self) -> None:
        module = _load_script()
        stats = asyncio.run(module.verify_batch(
            repo=_RecordingRepo([], states={1: _fact(1), 99: _fact(99)}),
            docs=[{"match_id": 1}],
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
            projection_states={1: _fact(1), 99: _fact(99)},
            scoped=True,
        ))

        self.assertEqual(stats["orphan"], 0)
        self.assertEqual(stats["orphan_check_skipped"], 1)

    def test_merge_stats_keeps_latest_watermark_instead_of_adding_it(self) -> None:
        module = _load_script()
        total = module._empty_backfill_stats()
        first = module._empty_backfill_stats()
        second = module._empty_backfill_stats()
        first["last_successful_match_id"] = 10
        second["last_successful_match_id"] = 20

        module.merge_stats(total, first)
        module.merge_stats(total, second)

        self.assertEqual(total["last_successful_match_id"], 20)

    def test_orphan_count_streams_fact_ids_and_checks_source_in_bounded_batches(self) -> None:
        module = _load_script()
        db = _OrphanCheckDb(
            source_docs=[{"match_id": 1}, {"match_id": 3}],
            fact_docs=[{"match_id": 1}, {"match_id": 2}, {"match_id": 3}, {"match_id": 4}],
        )

        orphan_count = asyncio.run(module._count_orphans_streaming(db, batch_size=2))

        self.assertEqual(orphan_count, 2)
        self.assertEqual(db.jjc_match_facts.find_calls, [({}, {"match_id": 1})])
        self.assertEqual(
            db.jjc_match_detail.find_calls,
            [
                ({"match_id": {"$in": [1, 2]}}, {"match_id": 1}),
                ({"match_id": {"$in": [3, 4]}}, {"match_id": 1}),
            ],
        )
        self.assertEqual([cursor.batch_size_value for cursor in db.jjc_match_facts.cursors], [2])
        self.assertEqual([cursor.batch_size_value for cursor in db.jjc_match_detail.cursors], [2, 2])

    def test_full_verify_uses_streaming_orphan_scan_after_source_batches(self) -> None:
        module = _load_script()
        module._log = lambda message: None
        db = _OrphanCheckDb(
            source_docs=[{"match_id": 1}, {"match_id": 2}],
            fact_docs=[{"match_id": 1}, {"match_id": 2}, {"match_id": 99}],
        )
        repo = _RecordingRepo([], states={1: _fact(1), 2: _fact(2)})

        stats = asyncio.run(module.run(
            module.validate_args(_args(verify_only=True, batch_size=2)),
            db=db, repo=repo,
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
        ))

        self.assertEqual(stats["source_scanned"], 2)
        self.assertEqual(stats["missing"], 0)
        self.assertEqual(stats["orphan"], 1)
        self.assertEqual(stats["orphan_check_skipped"], 0)
        self.assertEqual(repo.state_batches, [[1, 2]])
        self.assertEqual(db.jjc_match_facts.find_calls, [({}, {"match_id": 1})])
        self.assertEqual(
            db.jjc_match_detail.find_calls[-2:],
            [
                ({"match_id": {"$in": [1, 2]}}, {"match_id": 1}),
                ({"match_id": {"$in": [99]}}, {"match_id": 1}),
            ],
        )

    def test_run_streams_first_batch_before_cursor_is_exhausted(self) -> None:
        module = _load_script()
        module._log = lambda message: None
        events: List[Any] = []
        cursor = _FakeCursor([{"match_id": 1}, {"match_id": 2}, {"match_id": 3}], events)
        repo = _RecordingRepo(["inserted", "inserted", "inserted"], events=events)
        args = module.validate_args(_args(batch_size=2, apply=True, yes=True))

        asyncio.run(module.run(
            args,
            db=_FakeDb(cursor),
            repo=repo,
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
        ))

        self.assertLess(events.index(("apply", 1)), events.index(("yield", 3)))
        self.assertEqual(cursor.batch_size_value, 2)

    def test_long_backfill_cursor_disables_mongo_idle_timeout(self) -> None:
        module = _load_script()
        db = _FakeDb(_FakeCursor([]))

        asyncio.run(module.run(
            module.validate_args(_args()),
            db=db, repo=_RecordingRepo([]),
        ))

        self.assertTrue(db.jjc_match_detail.find_calls[0][1]["no_cursor_timeout"])

    def test_missing_only_apply_projects_absent_out_of_order_source_only(self) -> None:
        module = _load_script()
        module._log = lambda message: None
        cursor = _FakeCursor([{"match_id": 5}, {"match_id": 2}, {"match_id": 7}])
        repo = _RecordingRepo(["inserted"], states={5: _fact(5), 7: _fact(7)})

        stats = asyncio.run(module.run(
            module.validate_args(_args(batch_size=3, apply=True, yes=True, missing_only=True)),
            db=_FakeDb(cursor), repo=repo,
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
        ))

        self.assertEqual([fact["match_id"] for fact in repo.applied], [2])
        self.assertEqual(stats["scanned"], 1)
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(repo.state_batches, [[5, 2, 7]])

    def test_run_stops_before_later_batch_after_conflict_and_keeps_safe_watermark(self) -> None:
        module = _load_script()
        module._log = lambda message: None
        events: List[Any] = []
        cursor = _FakeCursor([{"match_id": match_id} for match_id in range(1, 6)], events)
        repo = _RecordingRepo(["inserted", "updated", "conflict"], events=events)

        stats = asyncio.run(module.run(
            module.validate_args(_args(batch_size=2, apply=True, yes=True)),
            db=_FakeDb(cursor), repo=repo,
            fact_builder=lambda match_id, payload, schema: _fact(match_id),
        ))

        self.assertEqual([fact["match_id"] for fact in repo.applied], [1, 2, 3])
        self.assertNotIn(("yield", 5), events)
        self.assertEqual(stats["last_successful_match_id"], 2)
        self.assertEqual(stats["blocking_failure"], 1)

    def test_run_creates_and_closes_injected_client_for_standalone_cli(self) -> None:
        module = _load_script()
        cursor = _FakeCursor([])
        db = _FakeDb(cursor)
        client = _FakeClient(db)
        args = module.validate_args(_args(mongo_uri="mongodb://example.invalid/jjc", db_name="jjc"))

        asyncio.run(module.run(
            args,
            repo=_RecordingRepo([]),
            client_factory=lambda uri, **kwargs: client,
        ))

        self.assertEqual(client.selected_name, "jjc")
        self.assertTrue(client.closed)

    def test_run_falls_back_to_jx3bot_when_uri_has_no_database(self) -> None:
        module = _load_script()

        class NoDefaultDatabaseClient(_FakeClient):
            def get_default_database(self, default: Any = None) -> Any:
                raise ConfigurationError("No default database name defined or provided")

        client = NoDefaultDatabaseClient(_FakeDb(_FakeCursor([])))
        asyncio.run(module.run(
            module.validate_args(_args(mongo_uri="mongodb://example.invalid")),
            repo=_RecordingRepo([]),
            client_factory=lambda uri, **kwargs: client,
        ))

        self.assertEqual(client.selected_name, "jx3bot")
        self.assertTrue(client.closed)

    def test_run_propagates_non_configuration_default_database_errors(self) -> None:
        module = _load_script()

        class UnexpectedDefaultDatabaseClient(_FakeClient):
            def get_default_database(self, default: Any = None) -> Any:
                raise RuntimeError("unexpected default database failure")

        client = UnexpectedDefaultDatabaseClient(_FakeDb(_FakeCursor([])))
        with self.assertRaisesRegex(RuntimeError, "unexpected default database failure"):
            asyncio.run(module.run(
                module.validate_args(_args(mongo_uri="mongodb://example.invalid")),
                repo=_RecordingRepo([]),
                client_factory=lambda uri, **kwargs: client,
            ))
        self.assertTrue(client.closed)

    def test_run_uses_config_uri_and_default_database_without_cli_uri(self) -> None:
        module = _load_script()
        db = _FakeDb(_FakeCursor([]))
        client = _FakeClient(db, default_db=db)
        module.get_mongo_uri = lambda: "mongodb://example.invalid/default-db"
        asyncio.run(module.run(
            module.validate_args(_args()), repo=_RecordingRepo([]),
            client_factory=lambda uri, **kwargs: client,
        ))
        self.assertTrue(client.closed)
        self.assertIsNone(client.selected_name)

    def test_run_does_not_boolean_check_uri_default_database(self) -> None:
        module = _load_script()

        class BoolRaisingDb(_FakeDb):
            def __bool__(self) -> bool:
                raise NotImplementedError("Motor Database objects do not implement truth value testing")

        db = BoolRaisingDb(_FakeCursor([]))
        client = _FakeClient(db, default_db=db)
        asyncio.run(module.run(
            module.validate_args(_args(mongo_uri="mongodb://example.invalid/default-db")),
            repo=_RecordingRepo([]),
            client_factory=lambda uri, **kwargs: client,
        ))

        self.assertTrue(client.closed)
        self.assertIsNone(client.selected_name)

    def test_source_projection_is_field_level_and_contains_all_fact_inputs(self) -> None:
        module = _load_script()
        db = _FakeDb(_FakeCursor([]))

        asyncio.run(module.run(
            module.validate_args(_args()), db=db, repo=_RecordingRepo([]),
        ))

        projection = db.jjc_match_detail.find_calls[0][0][1]
        expected_paths = {
            "_id",
            "match_id",
            "cached_at",
            "match_time",
            "matchTime",
            "start_time",
            "startTime",
            "time",
            "data.unavailable",
            "data.match_time",
            "data.matchTime",
            "data.start_time",
            "data.startTime",
            "data.time",
            "data.detail.unavailable",
            "data.detail.match_time",
            "data.detail.matchTime",
            "data.detail.start_time",
            "data.detail.startTime",
            "data.detail.time",
            "data.detail.match_type",
            "data.detail.matchType",
            "data.detail.type",
            "data.detail.map",
            "data.detail.map_name",
            "data.detail.duration",
            "data.detail.fight_seconds",
            "data.detail.basic_info.match_type",
            "data.detail.basic_info.matchTime",
            "data.detail.basic_info.map_name",
            "data.detail.basic_info.fight_seconds",
        }
        for basic_info_field in (
            "match_time", "matchTime", "start_time", "startTime", "time",
            "map", "map_name", "duration", "fight_seconds",
            "match_type", "matchType", "type",
        ):
            expected_paths.add("data.detail.basic_info.{}".format(basic_info_field))
        for detail_prefix in ("data", "data.detail"):
            for detail_field in (
                "map", "map_name", "duration", "fight_seconds",
                "match_type", "matchType", "type",
            ):
                expected_paths.add("{}.{}".format(detail_prefix, detail_field))
            for basic_info_field in (
                "match_time", "matchTime", "start_time", "startTime", "time",
                "map", "map_name", "duration", "fight_seconds",
                "match_type", "matchType", "type",
            ):
                expected_paths.add("{}.basic_info.{}".format(detail_prefix, basic_info_field))
            for team_key in ("team1", "team2"):
                expected_paths.add("{}.{}.won".format(detail_prefix, team_key))
                for player_key in ("players_info", "players"):
                    for field in ("role_name", "server", "kungfu_id", "kungfu", "total_score", "score"):
                        expected_paths.add("{}.{}.{}.{}".format(
                            detail_prefix, team_key, player_key, field
                        ))
        self.assertEqual(projection, {path: 0 if path == "_id" else 1 for path in expected_paths})


if __name__ == "__main__":
    unittest.main()
