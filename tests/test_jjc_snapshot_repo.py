from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from src.storage.mongo_repos.jjc_match_snapshot_repo import JjcMatchSnapshotRepo


class _AsyncIterMock:
    """Helper to mock Motor cursor async iteration."""

    def __init__(self, items: List[Dict[str, Any]]):
        self._items = list(items)

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _make_mock_collection(find_results=None):
    """Build a mock Motor collection with async update_one and find."""
    col = MagicMock()
    col.update_one = MagicMock()

    async def _update_one(filter_doc, update_doc, upsert=False):
        return MagicMock()

    col.update_one.side_effect = _update_one

    if find_results is not None:
        col.find = MagicMock(return_value=_AsyncIterMock(find_results))
    return col


class TestSaveEquipmentSnapshot(unittest.IsolatedAsyncioTestCase):
    async def test_new_snapshot_uses_upsert(self):
        col = _make_mock_collection()
        db = MagicMock()
        db.jjc_equipment_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        await repo.save_equipment_snapshot("hash_abc", [{"pos": 1, "name": "helm"}], seen_at=1234567890.0)

        col.update_one.assert_called_once()
        call_args, call_kwargs = col.update_one.call_args
        assert call_args[0] == {"snapshot_hash": "hash_abc"}
        assert call_kwargs.get("upsert") is True

    async def test_duplicate_hash_only_updates_last_seen_at(self):
        col = _make_mock_collection()
        db = MagicMock()
        db.jjc_equipment_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        await repo.save_equipment_snapshot("hash_abc", [{"pos": 1}], seen_at=1234567890.0)

        call_args, _ = col.update_one.call_args
        update_doc = call_args[1]
        # $setOnInsert contains armors — only applied on insert, not on duplicate update
        assert "$setOnInsert" in update_doc
        assert "armors" in update_doc["$setOnInsert"]
        assert update_doc["$setOnInsert"]["armors"] == [{"pos": 1}]
        # $set should contain last_seen_at
        assert "$set" in update_doc
        assert "last_seen_at" in update_doc["$set"]
        # armors must NOT be in $set (would overwrite on every call)
        assert "armors" not in update_doc.get("$set", {})

    async def test_save_without_seen_at_defaults_to_now(self):
        col = _make_mock_collection()
        db = MagicMock()
        db.jjc_equipment_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        await repo.save_equipment_snapshot("hash_abc", [{"pos": 2}])

        call_args, _ = col.update_one.call_args
        assert "last_seen_at" in call_args[1]["$set"]
        assert call_args[1]["$set"]["last_seen_at"] is not None


class TestSaveTalentSnapshot(unittest.IsolatedAsyncioTestCase):
    async def test_new_snapshot_uses_upsert(self):
        col = _make_mock_collection()
        db = MagicMock()
        db.jjc_talent_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        await repo.save_talent_snapshot("hash_xyz", [{"level": 1, "name": "奇穴A"}], seen_at=1234567890.0)

        col.update_one.assert_called_once()
        call_args, call_kwargs = col.update_one.call_args
        assert call_args[0] == {"snapshot_hash": "hash_xyz"}
        assert call_kwargs.get("upsert") is True

    async def test_duplicate_hash_uses_set_on_insert(self):
        col = _make_mock_collection()
        db = MagicMock()
        db.jjc_talent_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        await repo.save_talent_snapshot("hash_xyz", [{"level": 1}], seen_at=1234567890.0)

        call_args, _ = col.update_one.call_args
        update_doc = call_args[1]
        assert "$setOnInsert" in update_doc
        assert "talents" in update_doc["$setOnInsert"]
        assert "talents" not in update_doc.get("$set", {})


class TestLoadEquipmentSnapshots(unittest.IsolatedAsyncioTestCase):
    async def test_returns_hash_to_document_mapping(self):
        doc1 = {"snapshot_hash": "h1", "armors": [{"name": "a"}], "created_at": None}
        doc2 = {"snapshot_hash": "h2", "armors": [{"name": "b"}], "created_at": None}
        col = _make_mock_collection(find_results=[doc1, doc2])
        db = MagicMock()
        db.jjc_equipment_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        result = await repo.load_equipment_snapshots(["h1", "h2", "h3"])

        assert result == {"h1": doc1, "h2": doc2}
        assert "h3" not in result
        # Verify correct $in query
        col.find.assert_called_once_with({"snapshot_hash": {"$in": ["h1", "h2", "h3"]}})

    async def test_empty_input_returns_empty_dict(self):
        db = MagicMock()
        repo = JjcMatchSnapshotRepo(db=db)
        result = await repo.load_equipment_snapshots([])
        assert result == {}

    async def test_missing_hashes_return_empty_dict_no_exception(self):
        col = _make_mock_collection(find_results=[])
        db = MagicMock()
        db.jjc_equipment_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        result = await repo.load_equipment_snapshots(["nonexistent"])
        assert result == {}


class TestLoadTalentSnapshots(unittest.IsolatedAsyncioTestCase):
    async def test_returns_hash_to_document_mapping(self):
        doc = {"snapshot_hash": "t1", "talents": [{"level": 1}], "created_at": None}
        col = _make_mock_collection(find_results=[doc])
        db = MagicMock()
        db.jjc_talent_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        result = await repo.load_talent_snapshots(["t1"])

        assert result == {"t1": doc}

    async def test_empty_input_returns_empty_dict(self):
        db = MagicMock()
        repo = JjcMatchSnapshotRepo(db=db)
        result = await repo.load_talent_snapshots([])
        assert result == {}

    async def test_missing_hashes_return_empty_dict_no_exception(self):
        col = _make_mock_collection(find_results=[])
        db = MagicMock()
        db.jjc_talent_snapshot = col

        repo = JjcMatchSnapshotRepo(db=db)
        result = await repo.load_talent_snapshots(["nonexistent"])
        assert result == {}


if __name__ == "__main__":
    unittest.main()
