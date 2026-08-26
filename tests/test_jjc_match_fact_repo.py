from __future__ import annotations

import copy
import hashlib
import inspect
import unittest
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

from pymongo.errors import DuplicateKeyError

from src.infra.mongo import _ensure_indexes
from src.services.jx3.jjc_match_fact import build_match_fact, encode_combo_key
from src.storage.mongo_repos import jjc_match_fact_repo
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


def _team_players(kungfu_ids: List[int], scores: List[Optional[int]]) -> List[Dict[str, Any]]:
    return [
        {
            "kungfu_id": kungfu_id,
            "role_name": "role-{}".format(index),
            "server": "test",
            **({"total_score": score} if score is not None else {}),
        }
        for index, (kungfu_id, score) in enumerate(zip(kungfu_ids, scores), start=1)
    ]


def _matchup_fact(
    match_id: int,
    match_time: int,
    team1_kungfus: List[int],
    team2_kungfus: List[int],
    team1_scores: Optional[List[Optional[int]]] = None,
    team2_scores: Optional[List[Optional[int]]] = None,
    team1_won: bool = True,
) -> Dict[str, Any]:
    """Build a structurally faithful fact fixture for matchup aggregate tests."""
    if team1_scores is None:
        team1_scores = [2500, 2500, 2500]
    if team2_scores is None:
        team2_scores = [2500, 2500, 2500]
    return build_match_fact(
        match_id,
        {
            "cached_at": 1,
            "match_time": match_time,
            "map": "测试地图",
            "duration": 180,
            "match_type": 3,
            "team1": {
                "won": team1_won,
                "players": _team_players(team1_kungfus, team1_scores),
            },
            "team2": {
                "won": not team1_won,
                "players": _team_players(team2_kungfus, team2_scores),
            },
        },
        schema_version=1,
    )


def _matchup_tombstone(match_id: int) -> Dict[str, Any]:
    """Build the same compact inactive shape that the fact builder persists."""
    tombstone = build_match_fact(
        match_id,
        {"cached_at": 1, "unavailable": True},
        schema_version=1,
    )
    expected_fields = {
        "match_id",
        "active",
        "invalid_reason",
        "schema_version",
        "source_cached_at",
        "source_hash",
    }
    if set(tombstone) != expected_fields:
        raise AssertionError("matchup tombstone fixture must not retain query fields")
    return tombstone


class _FakeAggregateCollection:
    """Aggregate fake with a strict pipeline contract and independent oracle.

    The aggregate result still comes from a small fact-level reference evaluator
    rather than a Mongo implementation.  Before that evaluator runs, however,
    the received pipeline must match the complete candidate/direction/score/
    facet contract below.  A repo cannot pass by merely placing query values in
    unrelated stages.
    """

    def __init__(self, documents: Iterable[Dict[str, Any]]) -> None:
        self.documents = [copy.deepcopy(document) for document in documents]
        self.aggregate_calls: List[List[Dict[str, Any]]] = []
        self._filters: Optional[Dict[str, Any]] = None

    def expect_filters(self, filters: Dict[str, Any]) -> None:
        self._filters = copy.deepcopy(filters)

    @staticmethod
    def _contains(team: Dict[str, Any], kungfu_ids: List[int]) -> bool:
        return not kungfu_ids or encode_combo_key(kungfu_ids) in team["combo_keys"]

    @classmethod
    def _contains_expression(cls, kungfu_ids: List[int], team_path: str) -> Dict[str, Any]:
        if not kungfu_ids:
            return {"$literal": True}
        return {"$in": [encode_combo_key(kungfu_ids), team_path + ".combo_keys"]}

    @classmethod
    def _expected_pipeline_prefix(cls, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        team_a = filters["team_a_kungfu_ids"]
        team_b = filters["team_b_kungfu_ids"]
        candidate_match: Dict[str, Any] = {
            "active": True,
            "match_time": {"$gte": filters["start_time"], "$lt": filters["end_time"]},
        }
        if team_a or team_b:
            candidate_match["any_team_combo_keys"] = min(
                encode_combo_key(ids) for ids in (team_a, team_b) if ids
            )

        if team_a or team_b:
            forward = {
                "$and": [
                    cls._contains_expression(team_a, "$team1"),
                    cls._contains_expression(team_b, "$team2"),
                ]
            }
            reverse = {
                "$and": [
                    cls._contains_expression(team_a, "$team2"),
                    cls._contains_expression(team_b, "$team1"),
                ]
            }
            direction_candidate = {"$or": ["$_forward", "$_reverse"]}
        else:
            # Browsing all facts has no A/B direction, so this cannot be true.
            forward = {"$literal": False}
            reverse = {"$literal": False}
            direction_candidate = {"$literal": True}
        incomplete_score = {
            "$or": [
                {"$not": ["$team1.score_complete"]},
                {"$not": ["$team2.score_complete"]},
            ]
        }
        complete_in_range = {
            "$and": [
                "$team1.score_complete",
                "$team2.score_complete",
                {"$gte": ["$team1.score_sum", filters["score_min"] * 3]},
                {"$lt": ["$team1.score_sum", filters["score_max"] * 3]},
                {"$gte": ["$team2.score_sum", filters["score_min"] * 3]},
                {"$lt": ["$team2.score_sum", filters["score_max"] * 3]},
            ]
        }
        orientation_values = {
            "$concatArrays": [
                {"$cond": ["$_forward", ["forward"], []]},
                {"$cond": ["$_reverse", ["reverse"], []]},
            ]
        }
        bidirectional = {"$and": ["$_forward", "$_reverse"]}
        team_a_wins = {
            "$add": [
                {"$cond": [{"$and": ["$_forward", "$team1.won"]}, 1, 0]},
                {"$cond": [{"$and": ["$_reverse", "$team2.won"]}, 1, 0]},
            ]
        }
        team_b_wins = {
            "$add": [
                {"$cond": [{"$and": ["$_forward", "$team2.won"]}, 1, 0]},
                {"$cond": [{"$and": ["$_reverse", "$team1.won"]}, 1, 0]},
            ]
        }
        offset = (filters["page"] - 1) * filters["page_size"]
        return [
            {"$match": candidate_match},
            {"$sort": {"match_time": -1, "match_id": -1}},
            {"$set": {"_forward": forward, "_reverse": reverse}},
            {"$match": {"$expr": direction_candidate}},
            {
                "$facet": {
                    "missing": [
                        {"$match": {"$expr": incomplete_score}},
                        {"$count": "missing_score_match_count"},
                    ],
                    "statistics": [
                        {"$match": {"$expr": complete_in_range}},
                        {
                            "$group": {
                                "_id": None,
                                "match_count": {"$sum": 1},
                                "bidirectional_match_count": {
                                    "$sum": {"$cond": [bidirectional, 1, 0]}
                                },
                                "team_a_wins": {"$sum": team_a_wins},
                                "team_b_wins": {"$sum": team_b_wins},
                            }
                        },
                    ],
                    "total": [
                        {"$match": {"$expr": complete_in_range}},
                        {"$count": "total"},
                    ],
                    "items": [
                        {"$match": {"$expr": complete_in_range}},
                        {"$set": {"matched_orientations": orientation_values}},
                        {"$skip": offset},
                        {"$limit": filters["page_size"]},
                    ],
                }
            },
        ]

    @classmethod
    def _assert_pipeline_contract(
        cls, pipeline: List[Dict[str, Any]], filters: Dict[str, Any]
    ) -> None:
        expected_prefix = cls._expected_pipeline_prefix(filters)
        if pipeline[:len(expected_prefix)] != expected_prefix:
            raise AssertionError(
                "search pipeline must exactly implement candidate, direction, score, and facet stages"
            )
        facet = expected_prefix[-1]["$facet"]
        if any(
            "$sort" in stage
            for branch in facet.values()
            for stage in branch
        ):
            raise AssertionError("facet branches must not repeat the already-applied fact sort")

    @staticmethod
    def _facet_document(reference: Dict[str, Any]) -> Dict[str, Any]:
        """Encode the raw result as the one document returned by ``$facet``.

        ``$count`` emits no document for zero matches, while ``$group`` emits
        no statistics document when no complete fact survives.  Item documents
        retain the helper fields introduced before the facet, as real Mongo
        does; the repository must remove them while decoding its response.
        """
        statistics = reference["statistics"]
        facet_statistics = []
        if statistics["match_count"]:
            facet_statistics.append({
                "_id": None,
                "match_count": statistics["match_count"],
                "bidirectional_match_count": statistics["bidirectional_match_count"],
                "team_a_wins": statistics["team_a_wins"],
                "team_b_wins": statistics["team_b_wins"],
            })
        facet_missing = []
        if statistics["missing_score_match_count"]:
            facet_missing.append({
                "missing_score_match_count": statistics["missing_score_match_count"]
            })
        facet_total = []
        if reference["total"]:
            facet_total.append({"total": reference["total"]})
        facet_items = []
        for item in reference["items"]:
            facet_item = copy.deepcopy(item)
            facet_item["_forward"] = "forward" in facet_item["matched_orientations"]
            facet_item["_reverse"] = "reverse" in facet_item["matched_orientations"]
            facet_items.append(facet_item)
        return {
            "missing": facet_missing,
            "statistics": facet_statistics,
            "total": facet_total,
            "items": facet_items,
        }

    @classmethod
    def _evaluate_reference(cls, documents: Iterable[Dict[str, Any]], filters: Dict[str, Any]) -> Dict[str, Any]:
        team_a = filters["team_a_kungfu_ids"]
        team_b = filters["team_b_kungfu_ids"]
        score_min_sum = filters["score_min"] * 3
        score_max_sum = filters["score_max"] * 3
        missing_score_match_count = 0
        valid: List[Dict[str, Any]] = []

        for fact in documents:
            if not fact.get("active"):
                continue
            match_time = fact.get("match_time")
            if not filters["start_time"] <= match_time < filters["end_time"]:
                continue
            team1 = fact["team1"]
            team2 = fact["team2"]
            if team_a or team_b:
                forward = cls._contains(team1, team_a) and cls._contains(team2, team_b)
                reverse = cls._contains(team2, team_a) and cls._contains(team1, team_b)
                if not forward and not reverse:
                    continue
                orientations = (["forward"] if forward else []) + (["reverse"] if reverse else [])
            else:
                orientations = []

            if not team1["score_complete"] or not team2["score_complete"]:
                missing_score_match_count += 1
                continue
            if not (
                team1["score_sum"] >= score_min_sum
                and team2["score_sum"] >= score_min_sum
                and team1["score_sum"] < score_max_sum
                and team2["score_sum"] < score_max_sum
            ):
                continue
            item = copy.deepcopy(fact)
            item["matched_orientations"] = orientations
            valid.append(item)

        valid.sort(key=lambda item: (item["match_time"], item["match_id"]), reverse=True)
        match_count = len(valid)
        bidirectional_match_count = sum(
            item["matched_orientations"] == ["forward", "reverse"] for item in valid
        )
        team_a_wins = 0
        team_b_wins = 0
        for item in valid:
            team1_won = item["team1"]["won"]
            if "forward" in item["matched_orientations"]:
                team_a_wins += int(team1_won)
                team_b_wins += int(not team1_won)
            if "reverse" in item["matched_orientations"]:
                team_a_wins += int(not team1_won)
                team_b_wins += int(team1_won)

        offset = (filters["page"] - 1) * filters["page_size"]
        return {
            "statistics": {
                "match_count": match_count,
                "bidirectional_match_count": bidirectional_match_count,
                "team_a_wins": team_a_wins,
                "team_b_wins": team_b_wins,
                "missing_score_match_count": missing_score_match_count,
            },
            "items": valid[offset:offset + filters["page_size"]],
            "total": match_count,
        }

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> _AsyncCursor:
        if self._filters is None:
            raise AssertionError("test must set normalized filters before aggregate")
        pipeline_copy = copy.deepcopy(pipeline)
        self.aggregate_calls.append(pipeline_copy)
        self._assert_pipeline_contract(pipeline_copy, self._filters)
        return _AsyncCursor([
            self._facet_document(self._evaluate_reference(self.documents, self._filters))
        ])


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


class TestJjcMatchFactRepoArchitecture(unittest.TestCase):
    def test_repo_does_not_import_services(self) -> None:
        self.assertNotIn(
            "from src.services",
            inspect.getsource(jjc_match_fact_repo),
        )


class TestJjcMatchFactRepoMatchupSearch(unittest.IsolatedAsyncioTestCase):
    """RED contracts for the aggregate read model added by task 3.5."""

    def _filters(self, **overrides: Any) -> Dict[str, Any]:
        filters = {
            "start_time": 100,
            "end_time": 300,
            "score_min": 2400,
            "score_max": 2600,
            "team_a_kungfu_ids": [10080],
            "team_b_kungfu_ids": [10242],
            "page": 1,
            "page_size": 20,
        }
        filters.update(overrides)
        return filters

    async def _search(
        self, documents: Iterable[Dict[str, Any]], filters: Dict[str, Any]
    ) -> Dict[str, Any]:
        collection = _FakeAggregateCollection(documents)
        collection.expect_filters(filters)
        repo = JjcMatchFactRepo(db=SimpleNamespace(jjc_match_facts=collection))

        result = await repo.search_matchups(filters)

        self.assertEqual(len(collection.aggregate_calls), 1)
        self.assertEqual(set(result), {"statistics", "items", "total"})
        self.assertEqual(
            set(result["statistics"]),
            {
                "match_count",
                "bidirectional_match_count",
                "team_a_wins",
                "team_b_wins",
                "missing_score_match_count",
            },
        )
        for item in result["items"]:
            self.assertNotIn("_forward", item)
            self.assertNotIn("_reverse", item)
        return result

    async def test_candidate_matches_allow_other_four_kungfus_and_mixed_combo_sizes(self) -> None:
        documents = [
            _matchup_fact(901, 201, [10080, 10062, 10028], [10242, 10014, 10447]),
            _matchup_fact(902, 202, [10062, 10145, 10242], [10028, 10014, 10447]),
            _matchup_fact(903, 203, [10062, 10145, 10080], [10014, 10242, 10447]),
            _matchup_fact(904, 204, [10080, 10080, 10062], [10242, 10014, 10447]),
        ]

        single_result = await self._search(documents, self._filters())
        canghua_result = await self._search(
            documents,
            self._filters(
                team_a_kungfu_ids=[10062, 10145],
                team_b_kungfu_ids=[10028],
            ),
        )
        cang_qimingge_result = await self._search(
            documents,
            self._filters(
                team_a_kungfu_ids=[10062, 10145],
                team_b_kungfu_ids=[10014, 10242, 10447],
            ),
        )

        self.assertEqual(
            [item["match_id"] for item in single_result["items"]],
            [904, 903, 901],
        )
        self.assertEqual([item["match_id"] for item in canghua_result["items"]], [902])
        self.assertEqual(
            [item["match_id"] for item in cang_qimingge_result["items"]], [903]
        )

    async def test_candidate_requires_repeated_kungfu_occurrences(self) -> None:
        documents = [
            _matchup_fact(904, 204, [10080, 10080, 10062], [10242, 10014, 10447]),
            _matchup_fact(905, 205, [10080, 10062, 10028], [10242, 10014, 10447]),
        ]

        pair_result = await self._search(
            documents,
            self._filters(team_a_kungfu_ids=[10080, 10080]),
        )
        triple_result = await self._search(
            documents,
            self._filters(team_a_kungfu_ids=[10080, 10080, 10080]),
        )

        self.assertEqual([item["match_id"] for item in pair_result["items"]], [904])
        self.assertEqual(triple_result["items"], [])
        self.assertEqual(triple_result["statistics"], {
            "match_count": 0,
            "bidirectional_match_count": 0,
            "team_a_wins": 0,
            "team_b_wins": 0,
            "missing_score_match_count": 0,
        })
        self.assertEqual(triple_result["total"], 0)

    async def test_forward_reverse_and_bidirectional_stats_swap_when_configurations_swap(self) -> None:
        documents = [
            _matchup_fact(910, 210, [10080, 10062, 10028], [10242, 10014, 10447], team1_won=True),
            _matchup_fact(909, 209, [10242, 10014, 10447], [10080, 10062, 10028], team1_won=False),
            _matchup_fact(908, 208, [10080, 10242, 10062], [10080, 10242, 10028], team1_won=True),
        ]
        original = await self._search(documents, self._filters())
        swapped = await self._search(
            documents,
            self._filters(team_a_kungfu_ids=[10242], team_b_kungfu_ids=[10080]),
        )

        self.assertEqual(
            {
                item["match_id"]: item["matched_orientations"]
                for item in original["items"]
            },
            {
                910: ["forward"],
                909: ["reverse"],
                908: ["forward", "reverse"],
            },
        )
        self.assertEqual(original["statistics"], {
            "match_count": 3,
            "bidirectional_match_count": 1,
            "team_a_wins": 3,
            "team_b_wins": 1,
            "missing_score_match_count": 0,
        })
        self.assertEqual(
            {item["match_id"] for item in swapped["items"]},
            {item["match_id"] for item in original["items"]},
        )
        self.assertEqual(swapped["statistics"]["match_count"], 3)
        self.assertEqual(swapped["statistics"]["bidirectional_match_count"], 1)
        self.assertEqual(swapped["statistics"]["team_a_wins"], 1)
        self.assertEqual(swapped["statistics"]["team_b_wins"], 3)

    async def test_single_empty_side_and_equal_sides_use_the_same_direction_rules(self) -> None:
        documents = [
            _matchup_fact(920, 220, [10080, 10062, 10028], [10242, 10014, 10447], team1_won=True),
            _matchup_fact(919, 219, [10080, 10242, 10062], [10080, 10242, 10028], team1_won=True),
        ]
        single_empty = await self._search(
            documents,
            self._filters(team_a_kungfu_ids=[10080], team_b_kungfu_ids=[]),
        )
        equal_sides = await self._search(
            documents,
            self._filters(team_a_kungfu_ids=[10080], team_b_kungfu_ids=[10080]),
        )

        self.assertEqual(
            {item["match_id"]: item["matched_orientations"] for item in single_empty["items"]},
            {920: ["forward"], 919: ["forward", "reverse"]},
        )
        self.assertEqual(single_empty["statistics"]["match_count"], 2)
        self.assertEqual(single_empty["statistics"]["bidirectional_match_count"], 1)
        self.assertEqual(single_empty["statistics"]["team_a_wins"], 2)
        self.assertEqual(single_empty["statistics"]["team_b_wins"], 1)
        self.assertEqual(
            {item["match_id"]: item["matched_orientations"] for item in equal_sides["items"]},
            {919: ["forward", "reverse"]},
        )
        self.assertEqual(equal_sides["statistics"], {
            "match_count": 1,
            "bidirectional_match_count": 1,
            "team_a_wins": 1,
            "team_b_wins": 1,
            "missing_score_match_count": 0,
        })

    async def test_both_empty_browses_without_directions_and_counts_missing_scores(self) -> None:
        documents = [
            _matchup_fact(930, 230, [10080, 10062, 10028], [10242, 10014, 10447]),
            _matchup_fact(
                929,
                229,
                [10062, 10145, 10014],
                [10080, 10028, 10242],
                team1_scores=[2500, None, 2500],
            ),
            _matchup_tombstone(928),
        ]
        result = await self._search(
            documents,
            self._filters(team_a_kungfu_ids=[], team_b_kungfu_ids=[]),
        )

        self.assertEqual([item["match_id"] for item in result["items"]], [930])
        self.assertEqual(result["items"][0]["matched_orientations"], [])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["statistics"]["match_count"], 1)
        self.assertEqual(result["statistics"]["missing_score_match_count"], 1)
        self.assertEqual(result["statistics"]["bidirectional_match_count"], 0)
        self.assertEqual(result["statistics"]["team_a_wins"], 0)
        self.assertEqual(result["statistics"]["team_b_wins"], 0)

    async def test_only_matching_incomplete_fact_decodes_missing_facet_without_valid_totals(self) -> None:
        result = await self._search(
            [
                _matchup_fact(
                    925,
                    225,
                    [10080, 10062, 10028],
                    [10242, 10014, 10447],
                    team1_scores=[2500, None, 2500],
                )
            ],
            self._filters(),
        )

        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["statistics"], {
            "match_count": 0,
            "bidirectional_match_count": 0,
            "team_a_wins": 0,
            "team_b_wins": 0,
            "missing_score_match_count": 1,
        })

    async def test_time_score_bounds_and_missing_scores_are_filtered_by_exact_sums(self) -> None:
        documents = [
            _matchup_fact(940, 100, [10080, 10062, 10028], [10242, 10014, 10447], [2400] * 3, [2400] * 3),
            _matchup_fact(939, 150, [10080, 10062, 10028], [10242, 10014, 10447], [2600] * 3, [2600] * 3),
            _matchup_fact(938, 151, [10080, 10062, 10028], [10242, 10014, 10447], [2400] * 3, [2600] * 3),
            _matchup_fact(937, 152, [10080, 10062, 10028], [10242, 10014, 10447], [2500, None, 2500], [2500] * 3),
            _matchup_fact(934, 153, [10062, 10145, 10028], [10014, 10447, 10028], [2500, None, 2500], [2500] * 3),
            _matchup_fact(936, 200, [10080, 10062, 10028], [10242, 10014, 10447]),
            _matchup_tombstone(935),
        ]
        result = await self._search(documents, self._filters(start_time=100, end_time=200))

        self.assertEqual([item["match_id"] for item in result["items"]], [940])
        self.assertEqual(result["statistics"], {
            "match_count": 1,
            "bidirectional_match_count": 0,
            "team_a_wins": 1,
            "team_b_wins": 0,
            "missing_score_match_count": 1,
        })

    async def test_pages_are_unique_and_stable_across_a_bidirectional_fact(self) -> None:
        documents = [
            _matchup_fact(
                1100 + index,
                2000 + index,
                [10080, 10062, 10028],
                [10242, 10014, 10447],
            )
            for index in range(18)
        ]
        documents.extend([
            _matchup_fact(1701, 1500, [10080, 10062, 10028], [10242, 10014, 10447]),
            _matchup_fact(1700, 1500, [10080, 10062, 10028], [10242, 10014, 10447]),
            _matchup_fact(1600, 1499, [10080, 10062, 10028], [10242, 10014, 10447]),
            _matchup_fact(2000, 3000, [10080, 10242, 10062], [10080, 10242, 10028]),
        ])
        first_page = await self._search(documents, self._filters(
            start_time=1400,
            end_time=3100,
            page=1,
        ))
        second_page = await self._search(documents, self._filters(
            start_time=1400,
            end_time=3100,
            page=2,
        ))

        first_ids = [item["match_id"] for item in first_page["items"]]
        second_ids = [item["match_id"] for item in second_page["items"]]
        all_ids = first_ids + second_ids
        self.assertEqual(first_page["total"], 22)
        self.assertEqual(first_page["statistics"]["match_count"], 22)
        self.assertEqual(first_page["statistics"]["bidirectional_match_count"], 1)
        self.assertEqual(len(first_ids), 20)
        self.assertEqual(len(second_ids), 2)
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(first_ids, [2000] + list(range(1117, 1099, -1)) + [1701])
        self.assertEqual(second_ids, [1700, 1600])


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
