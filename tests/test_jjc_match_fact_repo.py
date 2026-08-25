from __future__ import annotations

import copy
import hashlib
import unittest
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

from pymongo.errors import DuplicateKeyError

from src.infra.mongo import _ensure_indexes
from src.storage.mongo_repos.jjc_match_fact_repo import JjcMatchFactRepo


class _AsyncCursor:
    def __init__(self, documents: Iterable[Dict[str, Any]]) -> None:
        self._documents = [copy.deepcopy(document) for document in documents]

    def __aiter__(self):
        self._iterator = iter(self._documents)
        return self

    async def __anext__(self) -> Dict[str, Any]:
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class _FakeMotorCollection:
    """Small in-memory Motor substitute that applies Mongo-style write filters."""

    def __init__(self) -> None:
        self.documents: Dict[int, Dict[str, Any]] = {}
        self.find_calls: List[Dict[str, Any]] = []
        self.replace_filters: List[Dict[str, Any]] = []
        self.race_replacement: Optional[Dict[str, Any]] = None

    @staticmethod
    def _matches(document: Dict[str, Any], filter_doc: Dict[str, Any]) -> bool:
        for field, expected in filter_doc.items():
            actual = document.get(field)
            if isinstance(expected, dict):
                if "$exists" in expected and (field in document) != bool(expected["$exists"]):
                    return False
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                continue
            if actual != expected:
                return False
        return True

    async def find_one(self, filter_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for document in self.documents.values():
            if self._matches(document, filter_doc):
                return copy.deepcopy(document)
        return None

    def find(self, filter_doc: Dict[str, Any]) -> _AsyncCursor:
        self.find_calls.append(copy.deepcopy(filter_doc))
        return _AsyncCursor(
            document for document in self.documents.values() if self._matches(document, filter_doc)
        )

    async def replace_one(
        self,
        filter_doc: Dict[str, Any],
        replacement: Dict[str, Any],
        upsert: bool = False,
    ) -> SimpleNamespace:
        self.replace_filters.append(copy.deepcopy(filter_doc))
        match_id = replacement["match_id"]
        if self.race_replacement is not None and "source_hash" in filter_doc:
            self.documents[match_id] = copy.deepcopy(self.race_replacement)
            self.race_replacement = None

        for current_id, document in list(self.documents.items()):
            if self._matches(document, filter_doc):
                stored = copy.deepcopy(replacement)
                if "_id" in stored and stored["_id"] != document.get("_id"):
                    raise ValueError("immutable _id cannot be changed by replacement")
                if "_id" not in stored and "_id" in document:
                    stored["_id"] = document["_id"]
                self.documents[current_id] = stored
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

        if upsert:
            if match_id in self.documents:
                raise DuplicateKeyError("duplicate match_id")
            replacement_id = replacement.get("_id")
            if replacement_id is not None and any(
                document.get("_id") == replacement_id
                for document in self.documents.values()
            ):
                raise DuplicateKeyError("duplicate _id")
            self.documents[match_id] = copy.deepcopy(replacement)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=match_id)
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)


class _FakeIndexCollection:
    """In-memory collection that records index lifecycle calls."""

    def __init__(self, indexes: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.indexes = copy.deepcopy(indexes or {})
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


def _source_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _active(
    match_id: int = 1001,
    cached_at: Any = 100.0,
    source_hash: Optional[str] = None,
    schema_version: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    document = {
        "match_id": match_id,
        "active": True,
        "invalid_reason": None,
        "match_time": 1710000000,
        "map": "白龙口",
        "duration": 180,
        "match_type": 3,
        "schema_version": schema_version,
        "source_cached_at": cached_at,
        "source_hash": source_hash or _source_hash("active"),
        "team1": {"combo_keys": ["v1:1:10080"], "score_sum": 3000},
        "team2": {"combo_keys": ["v1:1:10242"], "score_sum": 3300},
        "any_team_combo_keys": ["v1:1:10080", "v1:1:10242"],
        "min_team_score_sum": 3000,
        "max_team_score_sum": 3300,
    }
    document.update(overrides)
    return document


def _tombstone(
    match_id: int = 1001,
    cached_at: Any = 100.0,
    source_hash: Optional[str] = None,
    schema_version: int = 1,
    invalid_reason: str = "unavailable",
    **overrides: Any,
) -> Dict[str, Any]:
    document = {
        "match_id": match_id,
        "active": False,
        "invalid_reason": invalid_reason,
        "schema_version": schema_version,
        "source_cached_at": cached_at,
        "source_hash": source_hash or _source_hash("tombstone"),
    }
    document.update(overrides)
    return document


class TestJjcMatchFactRepo(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.collection = _FakeMotorCollection()
        self.repo = JjcMatchFactRepo(
            db=SimpleNamespace(jjc_match_facts=self.collection)
        )

    async def test_match_id_is_a_unique_bson_integer_key(self) -> None:
        self.assertEqual(JjcMatchFactRepo.COLLECTION_NAME, "jjc_match_facts")
        self.assertEqual(await self.repo.apply_projection(_active(match_id=1001)), "inserted")
        self.assertEqual(
            await self.repo.apply_projection(_active(match_id=1001, cached_at=101)),
            "updated",
        )
        self.assertEqual(list(self.collection.documents), [1001])
        self.assertIsInstance(self.collection.documents[1001]["match_id"], int)

    async def test_first_active_and_first_tombstone_have_stable_statuses(self) -> None:
        self.assertEqual(await self.repo.apply_projection(_active()), "inserted")
        self.assertEqual(
            await self.repo.apply_projection(_tombstone(match_id=1002)), "tombstoned"
        )
        self.assertEqual(self.collection.documents[1002], _tombstone(match_id=1002))

    async def test_newer_projection_replaces_active_and_tombstone_in_both_directions(self) -> None:
        self.assertEqual(await self.repo.apply_projection(_active(cached_at=100)), "inserted")
        self.assertEqual(
            await self.repo.apply_projection(_tombstone(cached_at=101)), "tombstoned"
        )
        self.assertFalse(self.collection.documents[1001]["active"])
        self.assertEqual(
            await self.repo.apply_projection(_active(cached_at=102, map="扬州")), "updated"
        )
        self.assertTrue(self.collection.documents[1001]["active"])
        self.assertEqual(self.collection.documents[1001]["map"], "扬州")

    async def test_older_projection_is_skipped_without_changing_tombstone(self) -> None:
        current = _tombstone(cached_at=200)
        self.collection.documents[1001] = copy.deepcopy(current)

        self.assertEqual(await self.repo.apply_projection(_active(cached_at=199)), "skipped_old")
        self.assertEqual(self.collection.documents[1001], current)

    async def test_equal_time_different_hash_is_conflict_without_write(self) -> None:
        current = _active(cached_at=200, source_hash=_source_hash("current"))
        self.collection.documents[1001] = copy.deepcopy(current)

        self.assertEqual(
            await self.repo.apply_projection(
                _active(cached_at=200, source_hash=_source_hash("incoming"))
            ),
            "conflict",
        )
        self.assertEqual(self.collection.documents[1001], current)

    async def test_equal_source_higher_schema_fully_rebuilds_and_clears_derived_fields(self) -> None:
        source_hash = _source_hash("same-source")
        self.collection.documents[1001] = _active(
            cached_at=200,
            source_hash=source_hash,
            schema_version=1,
            old_derived_field="must disappear",
        )
        rebuilt = _active(
            cached_at=200,
            source_hash=source_hash,
            schema_version=2,
            map="重建后地图",
        )

        self.assertEqual(await self.repo.apply_projection(rebuilt), "updated")
        self.assertEqual(self.collection.documents[1001], rebuilt)
        self.assertNotIn("old_derived_field", self.collection.documents[1001])

    async def test_tombstone_replacement_clears_all_query_and_summary_fields(self) -> None:
        self.collection.documents[1001] = _active(cached_at=100)
        tombstone = _tombstone(cached_at=101, extra_field="must be dropped")

        self.assertEqual(await self.repo.apply_projection(tombstone), "tombstoned")
        self.assertEqual(
            self.collection.documents[1001],
            _tombstone(cached_at=101),
        )

    async def test_equal_source_same_or_lower_schema_is_noop(self) -> None:
        source_hash = _source_hash("same-source")
        current = _active(cached_at=200, source_hash=source_hash, schema_version=3)
        self.collection.documents[1001] = copy.deepcopy(current)

        self.assertEqual(
            await self.repo.apply_projection(
                _active(cached_at=200, source_hash=source_hash, schema_version=3, map="new")
            ),
            "noop",
        )
        self.assertEqual(
            await self.repo.apply_projection(
                _active(cached_at=200, source_hash=source_hash, schema_version=2, map="older")
            ),
            "noop",
        )
        self.assertEqual(self.collection.documents[1001], current)

    async def test_conditional_replace_cannot_overwrite_a_newer_racing_projection(self) -> None:
        old_current = _active(cached_at=100, source_hash=_source_hash("old"))
        future_current = _tombstone(cached_at=300, source_hash=_source_hash("future"))
        self.collection.documents[1001] = copy.deepcopy(old_current)
        self.collection.race_replacement = future_current

        self.assertEqual(
            await self.repo.apply_projection(
                _active(cached_at=200, source_hash=_source_hash("incoming"))
            ),
            "skipped_old",
        )
        self.assertEqual(self.collection.documents[1001], future_current)

    async def test_input_document_is_not_modified_and_invalid_version_fields_raise(self) -> None:
        incoming = _tombstone(cached_at=100, extra_field="discarded")
        original = copy.deepcopy(incoming)
        self.assertEqual(await self.repo.apply_projection(incoming), "tombstoned")
        self.assertEqual(incoming, original)

        invalid_documents = [
            _active(match_id="1001"),
            _active(match_id=True),
            _active(schema_version=0),
            _active(schema_version=True),
            _active(cached_at=float("inf")),
            _active(cached_at=float("nan")),
            _active(cached_at=0),
            _active(cached_at=None),
            _active(source_hash="not-a-sha256"),
            _active(active="true"),
        ]
        for document in invalid_documents:
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    await self.repo.apply_projection(document)

    async def test_active_projection_discards_caller_id_before_cas_replacement(self) -> None:
        current = _active(cached_at=100)
        current["_id"] = "stored-id"
        incoming = _active(cached_at=101)
        incoming["_id"] = "caller-id"
        original = copy.deepcopy(incoming)
        self.collection.documents[1001] = copy.deepcopy(current)

        self.assertEqual(await self.repo.apply_projection(incoming), "updated")
        self.assertEqual(incoming, original)
        self.assertEqual(self.collection.documents[1001].get("_id"), "stored-id")
        self.assertNotEqual(self.collection.documents[1001].get("_id"), "caller-id")

    async def test_legacy_unversioned_match_is_repaired_with_stable_status(self) -> None:
        legacy_active = _active(match_id=1001)
        legacy_active.pop("source_cached_at")
        legacy_tombstone = _tombstone(match_id=1002)
        legacy_tombstone.pop("source_cached_at")
        self.collection.documents = {1001: legacy_active, 1002: legacy_tombstone}

        self.assertEqual(await self.repo.apply_projection(_active(match_id=1001)), "updated")
        self.assertEqual(
            await self.repo.apply_projection(_tombstone(match_id=1002)), "tombstoned"
        )

    async def test_positive_finite_float_source_watermarks_cover_double_boundaries(self) -> None:
        smallest_subnormal = float.fromhex("0x0.0000000000001p-1022")
        largest_finite = float.fromhex("0x1.fffffffffffffp+1023")

        self.assertEqual(
            await self.repo.apply_projection(_active(match_id=1001, cached_at=smallest_subnormal)),
            "inserted",
        )
        self.assertEqual(
            await self.repo.apply_projection(_active(match_id=1002, cached_at=largest_finite)),
            "inserted",
        )

    async def test_bson_integer_bounds_apply_to_match_id_and_integer_source_time(self) -> None:
        largest_bson_int = 2 ** 63 - 1
        self.assertEqual(
            await self.repo.apply_projection(
                _active(match_id=largest_bson_int, cached_at=largest_bson_int)
            ),
            "inserted",
        )
        for document in (
            _active(match_id=2 ** 63, cached_at=100),
            _active(match_id=1002, cached_at=2 ** 63),
        ):
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    await self.repo.apply_projection(document)

    async def test_get_projection_state_and_batch_read_use_integer_deduplicated_single_find(self) -> None:
        one = _active(match_id=1001)
        two = _tombstone(match_id=1002)
        self.collection.documents = {1001: copy.deepcopy(one), 1002: copy.deepcopy(two)}

        self.assertEqual(await self.repo.get_projection_state(1001), one)
        states = await self.repo.get_projection_states([1002, 1001, 1002])

        self.assertEqual(states, {1002: two, 1001: one})
        self.assertEqual(
            self.collection.find_calls,
            [{"match_id": {"$in": [1002, 1001]}}],
        )


class TestJjcMatchFactIndexes(unittest.IsolatedAsyncioTestCase):
    _ACTIVE_PARTIAL = {"active": True}
    _ARRAY_FIELDS = {
        "any_team_combo_keys",
        "team1.kungfu_ids",
        "team2.kungfu_ids",
        "team1.combo_keys",
        "team2.combo_keys",
        "combo_keys",
    }

    @classmethod
    def _expected_indexes(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "idx_match_id": {
                "key": [("match_id", 1)],
                "unique": True,
            },
            "idx_active_combo_time": {
                "key": [
                    ("any_team_combo_keys", 1),
                    ("match_time", -1),
                    ("match_id", -1),
                ],
                "partialFilterExpression": cls._ACTIVE_PARTIAL,
            },
            "idx_active_time": {
                "key": [("match_time", -1), ("match_id", -1)],
                "partialFilterExpression": cls._ACTIVE_PARTIAL,
            },
        }

    @staticmethod
    def _matches_partial(document: Dict[str, Any], partial: Dict[str, Any]) -> bool:
        return all(document.get(field) == expected for field, expected in partial.items())

    async def test_match_fact_query_indexes_have_exact_active_contract(self) -> None:
        db = _FakeIndexDatabase()

        await _ensure_indexes(db)

        collection = db["jjc_match_facts"]
        created = {
            call["name"]: {"key": call["keys"], **call["kwargs"]}
            for call in collection.create_calls
        }
        self.assertEqual(created, self._expected_indexes())
        for name in ("idx_active_combo_time", "idx_active_time"):
            indexed_array_fields = [
                field for field, _ in created[name]["key"] if field in self._ARRAY_FIELDS
            ]
            self.assertLessEqual(len(indexed_array_fields), 1, name)
        self.assertFalse(
            self._matches_partial({"active": False}, self._ACTIVE_PARTIAL)
        )

    async def test_partial_definition_change_rebuilds_match_fact_index(self) -> None:
        expected = self._expected_indexes()["idx_active_combo_time"]
        for previous_partial in (None, {"active": False}):
            with self.subTest(previous_partial=previous_partial):
                db = _FakeIndexDatabase()
                existing = copy.deepcopy(expected)
                if previous_partial is None:
                    existing.pop("partialFilterExpression")
                else:
                    existing["partialFilterExpression"] = previous_partial
                db["jjc_match_facts"].indexes["idx_active_combo_time"] = existing

                await _ensure_indexes(db)

                collection = db["jjc_match_facts"]
                self.assertIn("idx_active_combo_time", collection.drop_calls)
                rebuilt = [
                    call
                    for call in collection.create_calls
                    if call["name"] == "idx_active_combo_time"
                ]
                self.assertEqual(
                    rebuilt,
                    [
                        {
                            "keys": expected["key"],
                            "name": "idx_active_combo_time",
                            "kwargs": {
                                "partialFilterExpression": self._ACTIVE_PARTIAL,
                            },
                        }
                    ],
                )

    async def test_identical_match_fact_index_definitions_are_not_dropped(self) -> None:
        db = _FakeIndexDatabase()
        db["jjc_match_facts"].indexes = self._expected_indexes()

        await _ensure_indexes(db)

        self.assertEqual(db["jjc_match_facts"].drop_calls, [])


if __name__ == "__main__":
    unittest.main()
