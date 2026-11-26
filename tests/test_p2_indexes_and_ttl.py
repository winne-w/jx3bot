from __future__ import annotations

import copy
import py_compile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import patch

from bson import ObjectId

from scripts.audit_mongo_indexes import (
    LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES,
    run_audit,
    summarize_index_audit,
)
from src.infra.mongo import EQUIPMENT_READ_V1_INDEXES, _ensure_indexes
from src.storage.mongo_repos.jjc_sync_repo import (
    JjcSyncRepo,
    calculate_match_fail_backoff,
    calculate_role_fail_backoff,
)
from src.storage.mongo_repos.server_master_repo import ServerMasterCacheRepo


class _FakeIndexCollection:
    def __init__(self, indexes: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.indexes: Dict[str, Dict[str, Any]] = copy.deepcopy(indexes or {})
        self.create_calls: List[Dict[str, Any]] = []
        self.drop_calls: List[str] = []

    async def index_information(self) -> Dict[str, Dict[str, Any]]:
        return copy.deepcopy(self.indexes)

    async def drop_index(self, name: str) -> None:
        self.drop_calls.append(name)
        self.indexes.pop(name, None)

    async def create_index(self, keys: Any, *, name: str, **kwargs: Any) -> str:
        normalized_keys = keys if isinstance(keys, list) else [(keys, 1)]
        self.create_calls.append(
            {"keys": normalized_keys, "name": name, "kwargs": copy.deepcopy(kwargs)}
        )
        self.indexes[name] = {"key": normalized_keys, **copy.deepcopy(kwargs)}
        return name


class _FakeIndexDatabase:
    def __init__(self) -> None:
        self.collections: Dict[str, _FakeIndexCollection] = {}

    def __getitem__(self, name: str) -> _FakeIndexCollection:
        return self.collections.setdefault(name, _FakeIndexCollection())

    def __getattr__(self, name: str) -> _FakeIndexCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


class _FakeServerMasterCollection:
    def __init__(self) -> None:
        self.docs: Dict[str, Dict[str, Any]] = {}
        self.last_update: Optional[Dict[str, Any]] = None

    async def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        doc = self.docs.get(query["key"])
        return copy.deepcopy(doc) if doc is not None else None

    async def update_one(
        self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False
    ) -> SimpleNamespace:
        self.last_update = copy.deepcopy(update)
        doc = self.docs.get(query["key"], {"key": query["key"]})
        doc.update(copy.deepcopy(update.get("$set", {})))
        self.docs[query["key"]] = doc
        return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

    async def delete_one(self, query: Dict[str, Any]) -> SimpleNamespace:
        existed = self.docs.pop(query["key"], None) is not None
        return SimpleNamespace(deleted_count=1 if existed else 0)


class _AsyncCursor:
    def __init__(self, docs: Iterable[Dict[str, Any]]) -> None:
        self._docs = list(docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self) -> Dict[str, Any]:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _FakeAuditCollection:
    def __init__(
        self,
        *,
        indexes: Optional[Dict[str, Dict[str, Any]]] = None,
        aggregate_rows: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._indexes = copy.deepcopy(indexes or {})
        self._aggregate_rows = copy.deepcopy(aggregate_rows or [])
        self.pipelines: List[List[Dict[str, Any]]] = []

    async def index_information(self) -> Dict[str, Dict[str, Any]]:
        return copy.deepcopy(self._indexes)

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> _AsyncCursor:
        self.pipelines.append(copy.deepcopy(pipeline))
        return _AsyncCursor(self._aggregate_rows)


class _FakeAuditDatabase:
    def __init__(self, collections: Dict[str, _FakeAuditCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeAuditCollection:
        return self._collections[name]


class TestP2IndexesAndTtl(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_indexes_declares_date_ttl_and_identity_id_and_drops_redundant_prefixes(
        self,
    ) -> None:
        db = _FakeIndexDatabase()
        with patch("config.JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 0):
            await _ensure_indexes(db)

        for col_name in ("server_master_cache", "jjc_role_recent"):
            calls = {call["name"]: call for call in db[col_name].create_calls}
            self.assertIn("idx_expires_at_dt", calls)
            self.assertEqual(calls["idx_expires_at_dt"]["keys"], [("expires_at_dt", 1)])
            self.assertEqual(calls["idx_expires_at_dt"]["kwargs"], {"expireAfterSeconds": 0})
            self.assertIn("idx_cached_at", calls)
            self.assertNotIn("expireAfterSeconds", calls["idx_cached_at"]["kwargs"])

        for col_name in ("role_jjc_cache", "jjc_role_indicator"):
            calls = {call["name"]: call for call in db[col_name].create_calls}
            self.assertIn("idx_identity_id", calls)
            self.assertEqual(calls["idx_identity_id"]["keys"], [("identity_id", 1)])
            self.assertEqual(
                calls["idx_identity_id"]["kwargs"],
                {"partialFilterExpression": {"identity_id": {"$exists": True}}},
            )

        participant_names = {call["name"] for call in db["jjc_match_participants"].create_calls}
        self.assertIn("idx_match_global_id", participant_names)
        self.assertNotIn("idx_match_id", participant_names)

        wanbaolou_names = {call["name"] for call in db["wanbaolou_subscriptions"].create_calls}
        self.assertIn("idx_user_item", wanbaolou_names)
        self.assertNotIn("idx_user_id", wanbaolou_names)

        stat_detail_names = {call["name"] for call in db["jjc_ranking_stat_details"].create_calls}
        self.assertIn("idx_timestamp_range_lane_kungfu", stat_detail_names)
        self.assertNotIn("idx_timestamp", stat_detail_names)
        self.assertNotIn("idx_timestamp_range_lane", stat_detail_names)

    async def test_server_master_repo_put_writes_utc_expires_at_dt_and_preserves_get(self) -> None:
        col = _FakeServerMasterCollection()
        db = SimpleNamespace(server_master_cache=col)
        ttl_seconds = 3600
        repo = ServerMasterCacheRepo(db=db, ttl_seconds=ttl_seconds)

        before = datetime.now(timezone.utc)
        await repo.put("梦江南", {"name": "梦江南", "zone": "电信五区", "id": "0501"})
        after = datetime.now(timezone.utc)

        stored = col.docs["梦江南"]
        self.assertIn("cached_at", stored)
        self.assertIsInstance(stored["cached_at"], int)
        self.assertIn("expires_at_dt", stored)
        expires_at_dt = stored["expires_at_dt"]
        self.assertIsInstance(expires_at_dt, datetime)
        self.assertEqual(expires_at_dt.tzinfo, timezone.utc)
        self.assertGreaterEqual(expires_at_dt, before + timedelta(seconds=ttl_seconds))
        self.assertLessEqual(expires_at_dt, after + timedelta(seconds=ttl_seconds))

        loaded = await repo.get("梦江南")
        self.assertEqual(loaded, {"name": "梦江南", "zone": "电信五区", "id": "0501"})


class TestP2BackoffHelpers(unittest.IsolatedAsyncioTestCase):
    def test_calculate_role_fail_backoff_schedule(self) -> None:
        self.assertEqual(calculate_role_fail_backoff(0), 0)
        self.assertEqual(calculate_role_fail_backoff(1), 0)
        self.assertEqual(calculate_role_fail_backoff(2), 0)
        self.assertEqual(calculate_role_fail_backoff(3), 1800)
        self.assertEqual(calculate_role_fail_backoff(5), 1800)

    def test_calculate_match_fail_backoff_schedule(self) -> None:
        self.assertEqual(calculate_match_fail_backoff(0), 300)
        self.assertEqual(calculate_match_fail_backoff(1), 300)
        self.assertEqual(calculate_match_fail_backoff(2), 1800)
        self.assertEqual(calculate_match_fail_backoff(3), 7200)
        self.assertEqual(calculate_match_fail_backoff(4), 21600)
        self.assertEqual(calculate_match_fail_backoff(10), 21600)

    async def test_release_failures_and_match_detail_failed_reuse_unified_backoff(self) -> None:
        from tests.test_jjc_sync_worker_queue import MemoryCollection, MemoryDb

        base_now = 1800000000.0
        identity_id = ObjectId()
        db = MemoryDb(
            roles=[
                {
                    "identity_key": "global:legacy-role",
                    "status": "syncing",
                    "lease_owner": "w1",
                    "lease_expires_at": base_now + 60.0,
                    "fail_count": 2,
                }
            ],
            matches=[
                {
                    "match_id": 42,
                    "status": "detail_syncing",
                    "lease_owner": "w1",
                    "lease_expires_at": base_now + 60.0,
                    "fail_count": 2,
                }
            ],
        )
        repo = JjcSyncRepo(db=db)

        with patch("src.storage.mongo_repos.jjc_sync_repo.time.time", return_value=base_now):
            self.assertTrue(
                await repo.release_role_failure(
                    "global:legacy-role", error_message="boom", lease_owner="w1"
                )
            )
            self.assertTrue(
                await repo.mark_match_detail_failed(
                    42, error_message="timeout", lease_owner="w1"
                )
            )

        role_row = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(role_row["status"], "failed")
        self.assertEqual(role_row["fail_count"], 3)
        self.assertEqual(role_row["next_sync_after"], base_now + 1800)

        match_row = db.jjc_sync_match_seen.docs[0]
        self.assertEqual(match_row["status"], "failed")
        self.assertEqual(match_row["fail_count"], 3)
        self.assertEqual(match_row["detail_retry_after"], base_now + 7200)

        # Verify identity queue path as well
        db.jjc_sync_identity_queue = MemoryCollection(
            [
                {
                    "identity_id": identity_id,
                    "identity_key": "global_id:99",
                    "status": "syncing",
                    "lease_owner": "w2",
                    "lease_expires_at": base_now + 60.0,
                    "fail_count": 1,
                }
            ]
        )
        with patch("src.storage.mongo_repos.jjc_sync_repo.time.time", return_value=base_now):
            self.assertTrue(
                await repo.release_identity_failure(
                    identity_id, error_message="transient", lease_owner="w2"
                )
            )
        id_row = db.jjc_sync_identity_queue.docs[0]
        self.assertEqual(id_row["status"], "pending")
        self.assertEqual(id_row["fail_count"], 2)
        self.assertIsNone(id_row["next_sync_after"])


class TestAuditMongoIndexesScript(unittest.IsolatedAsyncioTestCase):
    def test_summarize_index_audit_flags_zero_ops_legacy_and_mixed_types(self) -> None:
        index_stats = [
            {"name": "_id_", "accesses": {"ops": 0}},
            {"name": "idx_match_id", "accesses": {"ops": 120}},
            {"name": LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES[0], "accesses": {"ops": 0}},
            {"name": LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES[1], "accesses": {"ops": 5}},
            {"name": LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES[2], "accesses": {"ops": 0}},
        ]
        equipment_check = {
            "ready": False,
            "missing": ["idx_equipment_winner_latest_v1"],
            "mismatched": [],
        }
        type_counts = {
            "jjc_equipment_snapshot.last_seen_at": {"double": 50, "date": 3},
            "jjc_talent_snapshot.last_seen_at": {"double": 80, "missing": 1},
            "jjc_peak_score_rankings.updated_at": {"date": 12},
        }

        summary = summarize_index_audit(index_stats, equipment_check, type_counts)

        self.assertEqual(summary["match_detail_index_ops"]["idx_match_id"], 120)
        self.assertEqual(
            summary["zero_ops_legacy_multikey_indexes"],
            [
                LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES[0],
                LEGACY_MATCH_DETAIL_MULTIKEY_INDEXES[2],
            ],
        )
        self.assertFalse(summary["equipment_read_indexes"]["ready"])
        self.assertEqual(
            summary["equipment_read_indexes"]["missing"],
            ["idx_equipment_winner_latest_v1"],
        )
        self.assertEqual(
            summary["mixed_time_fields"],
            ["jjc_equipment_snapshot.last_seen_at"],
        )
        self.assertTrue(
            summary["time_field_types"]["jjc_equipment_snapshot.last_seen_at"]["has_mixed_types"]
        )
        self.assertFalse(
            summary["time_field_types"]["jjc_talent_snapshot.last_seen_at"]["has_mixed_types"]
        )
        self.assertFalse(
            summary["time_field_types"]["jjc_peak_score_rankings.updated_at"]["has_mixed_types"]
        )

    async def test_run_audit_executes_read_only_aggregations_and_equipment_verify(self) -> None:
        ready_indexes = {
            name: {"key": copy.deepcopy(keys)} for name, keys in EQUIPMENT_READ_V1_INDEXES
        }
        match_detail_col = _FakeAuditCollection(
            indexes=ready_indexes,
            aggregate_rows=[
                {"name": "idx_match_id", "accesses": {"ops": 99}},
                {"name": "idx_replay_player_role_id", "accesses": {"ops": 0}},
            ],
        )
        equip_snap_col = _FakeAuditCollection(
            aggregate_rows=[{"_id": "double", "count": 10}, {"_id": "date", "count": 2}]
        )
        talent_snap_col = _FakeAuditCollection(
            aggregate_rows=[{"_id": "double", "count": 10}]
        )
        peak_col = _FakeAuditCollection(
            aggregate_rows=[{"_id": "date", "count": 4}]
        )
        db = _FakeAuditDatabase(
            {
                "jjc_match_detail": match_detail_col,
                "jjc_equipment_snapshot": equip_snap_col,
                "jjc_talent_snapshot": talent_snap_col,
                "jjc_peak_score_rankings": peak_col,
            }
        )

        summary = await run_audit(db)
        self.assertTrue(summary["equipment_read_indexes"]["ready"])
        self.assertEqual(summary["zero_ops_legacy_multikey_indexes"], ["idx_replay_player_role_id"])
        self.assertEqual(summary["mixed_time_fields"], ["jjc_equipment_snapshot.last_seen_at"])
        self.assertEqual(match_detail_col.pipelines, [[{"$indexStats": {}}]])

    def test_audit_script_compiles_cleanly(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "audit_mongo_indexes.py"
        compiled = py_compile.compile(str(script_path), doraise=True)
        self.assertTrue(bool(compiled))


if __name__ == "__main__":
    unittest.main()
