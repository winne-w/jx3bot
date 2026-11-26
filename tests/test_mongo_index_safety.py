from __future__ import annotations

import copy
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.infra.mongo import (
    EQUIPMENT_READ_V1_INDEXES,
    _ensure_indexes,
    ensure_equipment_read_indexes,
    verify_equipment_read_indexes,
)


class _FakeIndexCollection:
    """In-memory Motor collection double recording index operations."""

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


class TestMongoIndexSafety(unittest.IsolatedAsyncioTestCase):
    async def test_unique_index_mismatch_never_drops_or_recreates(self) -> None:
        # Case 1: existing unique=True, definition differs on key / partialFilterExpression
        db = _FakeIndexDatabase()
        db["role_identities"].indexes["idx_global_id"] = {
            "key": [("global_id", 1)],
            "unique": True,
            "partialFilterExpression": {"global_id": {"$exists": True}},
        }
        # Case 2: existing unique=False, desired unique=True
        db["status_cache"].indexes["idx_cache_name"] = {
            "key": [("cache_name", 1)],
        }

        with patch("src.infra.mongo.logger") as mock_logger, patch(
            "config.JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 0
        ):
            await _ensure_indexes(db)

        self.assertEqual(db["role_identities"].drop_calls, [])
        self.assertNotIn(
            "idx_global_id",
            [call["name"] for call in db["role_identities"].create_calls],
        )
        self.assertEqual(
            db["role_identities"].indexes["idx_global_id"]["partialFilterExpression"],
            {"global_id": {"$exists": True}},
        )

        self.assertEqual(db["status_cache"].drop_calls, [])
        self.assertNotIn(
            "idx_cache_name",
            [call["name"] for call in db["status_cache"].create_calls],
        )
        self.assertGreaterEqual(mock_logger.error.call_count, 2)

    async def test_verify_equipment_read_indexes_missing_mismatched_and_ready(self) -> None:
        db = _FakeIndexDatabase()

        # 1. Missing all
        missing_report = await verify_equipment_read_indexes(db)
        self.assertFalse(missing_report["ready"])
        self.assertEqual(
            missing_report["missing"],
            [name for name, _ in EQUIPMENT_READ_V1_INDEXES],
        )
        self.assertEqual(missing_report["mismatched"], [])
        self.assertEqual(db["jjc_match_detail"].create_calls, [])
        self.assertEqual(db["jjc_match_detail"].drop_calls, [])

        # 2. Mismatched (one wrong key direction, two valid)
        first_name, _ = EQUIPMENT_READ_V1_INDEXES[0]
        db["jjc_match_detail"].indexes[first_name] = {
            "key": [("equipment_winner_gids_v1", 1), ("equipment_read_time_v1", 1)],
        }
        for name, keys in EQUIPMENT_READ_V1_INDEXES[1:]:
            db["jjc_match_detail"].indexes[name] = {"key": copy.deepcopy(keys)}

        mismatch_report = await verify_equipment_read_indexes(db)
        self.assertFalse(mismatch_report["ready"])
        self.assertEqual(mismatch_report["missing"], [])
        self.assertEqual(len(mismatch_report["mismatched"]), 1)
        self.assertEqual(mismatch_report["mismatched"][0]["name"], first_name)

        # 3. Ready after ensure_equipment_read_indexes rebuilds non-unique mismatch
        await ensure_equipment_read_indexes(db)
        self.assertIn(first_name, db["jjc_match_detail"].drop_calls)

        ready_report = await verify_equipment_read_indexes(db)
        self.assertTrue(ready_report["ready"])
        self.assertEqual(ready_report["missing"], [])
        self.assertEqual(ready_report["mismatched"], [])

    async def test_ensure_indexes_respects_local_win_equipment_flag(self) -> None:
        equipment_index_names = {name for name, _ in EQUIPMENT_READ_V1_INDEXES}

        db_disabled = _FakeIndexDatabase()
        with patch("config.JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 0):
            await _ensure_indexes(db_disabled)
        created_disabled = {
            call["name"] for call in db_disabled["jjc_match_detail"].create_calls
        }
        self.assertTrue(equipment_index_names.isdisjoint(created_disabled))

        db_enabled = _FakeIndexDatabase()
        with patch("config.JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 1):
            await _ensure_indexes(db_enabled)
        created_enabled = {
            call["name"]: call for call in db_enabled["jjc_match_detail"].create_calls
        }
        for name, expected_keys in EQUIPMENT_READ_V1_INDEXES:
            self.assertIn(name, created_enabled)
            self.assertEqual(created_enabled[name]["keys"], expected_keys)
            self.assertEqual(created_enabled[name]["kwargs"], {})

    async def test_numeric_cached_at_indexes_have_no_expire_after_seconds(self) -> None:
        db = _FakeIndexDatabase()
        with patch("config.JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 0):
            await _ensure_indexes(db)

        for col_name in ("server_master_cache", "jjc_role_recent"):
            calls = {call["name"]: call for call in db[col_name].create_calls}
            self.assertIn("idx_cached_at", calls)
            self.assertEqual(calls["idx_cached_at"]["keys"], [("cached_at", 1)])
            self.assertNotIn("expireAfterSeconds", calls["idx_cached_at"]["kwargs"])

    async def test_legacy_sync_role_queue_only_declares_identity_key_index(self) -> None:
        db = _FakeIndexDatabase()
        with patch("config.JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 0):
            await _ensure_indexes(db)

        calls = db["jjc_sync_role_queue"].create_calls
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "idx_identity_key")
        self.assertEqual(calls[0]["keys"], [("identity_key", 1)])
        self.assertEqual(calls[0]["kwargs"], {"unique": True})


if __name__ == "__main__":
    unittest.main()
