"""I01/I02/I03/I06: narrow result publication contract; Mongo races are separate."""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from bson import ObjectId

from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo, _snapshot_filter


_MISSING = object()


def field_value(doc, path):
    current = doc
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def expression_value(doc, expression):
    if isinstance(expression, str) and expression.startswith("$"):
        return field_value(doc, expression[1:])
    if not isinstance(expression, dict):
        return expression
    operator, value = next(iter(expression.items()))
    if operator == "$type":
        item = expression_value(doc, value)
        if item is _MISSING:
            return "missing"
        if type(item) is int:
            return "int"
        return {dict: "object", list: "array", bool: "bool", float: "double",
                str: "string", type(None): "null"}.get(type(item), "other")
    if operator == "$and":
        return all(expression_value(doc, item) for item in value)
    left, right = [expression_value(doc, item) for item in value]
    if operator == "$eq":
        return left == right
    if operator == "$in":
        return left in right
    if operator == "$gt":
        return left > right
    if operator == "$lt":
        return left < right
    raise AssertionError("test expression needs support for %s" % operator)


def matches(doc, query):
    for key, condition in query.items():
        if key == "$expr":
            if not expression_value(doc, condition):
                return False
            continue
        if key == "$and":
            if not all(matches(doc, term) for term in condition):
                return False
            continue
        if key == "$or":
            if not any(matches(doc, term) for term in condition):
                return False
            continue
        value = field_value(doc, key)
        if not isinstance(condition, dict):
            if value is _MISSING or value != condition:
                return False
            continue
        for op, expected in condition.items():
            if op == "$exists":
                if (value is not _MISSING) != expected:
                    return False
            elif op == "$eq":
                if value is _MISSING or value != expected:
                    return False
            elif op == "$lt":
                if value is _MISSING or isinstance(value, bool) or not isinstance(value, (int, float)) or value >= expected:
                    return False
            elif op == "$gt":
                if value is _MISSING or isinstance(value, bool) or not isinstance(value, (int, float)) or value <= expected:
                    return False
            elif op == "$gte":
                if value is _MISSING or isinstance(value, bool) or not isinstance(value, (int, float)) or value < expected:
                    return False
            elif op == "$type":
                allowed = expected if isinstance(expected, list) else [expected]
                if not any((name in ("int", "long", 16, 18) and type(value) is int)
                           or (name in ("object", 3) and isinstance(value, dict))
                           for name in allowed):
                    return False
            else:
                raise AssertionError("test matcher needs support for operator %s" % op)
    return True


class ResultCollection:
    def __init__(self, doc):
        self.doc = copy.deepcopy(doc)
        self.update_one = AsyncMock(side_effect=self.update)
        self.find_one = AsyncMock(side_effect=self.find)

    async def find(self, query, *args, **kwargs):
        return copy.deepcopy(self.doc) if self.doc is not None and matches(self.doc, query) else None

    async def update(self, query, update, *args, **kwargs):
        if self.doc is None or not matches(self.doc, query):
            return SimpleNamespace(matched_count=0, modified_count=0)
        if set(update) != {"$set"} or set(update["$set"]) != {"jjc_kungfu"}:
            raise AssertionError("publication must only set jjc_kungfu")
        self.doc["jjc_kungfu"] = copy.deepcopy(update["$set"]["jjc_kungfu"])
        return SimpleNamespace(matched_count=1, modified_count=1)


class RoleIdentityKungfuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.identity_id = ObjectId()
        self.before = {"_id": self.identity_id, "identity_key": "game:z:role-a",
                       "identity_level": "game_role", "server": "server-a", "name": "role-a",
                       "zone": "z", "game_role_id": "role-a", "role_id": "role-a",
                       "updated_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
                       "last_seen_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
                       "role_info_observed_match_time": 100}
        self.locator = {key: self.before[key] for key in
                        ("server", "name", "zone", "game_role_id", "role_id")}
        self.collection = ResultCollection(self.before)
        self.history = SimpleNamespace(insert_one=AsyncMock())
        self.repo = RoleIdentityRepo(db=SimpleNamespace(role_identities=self.collection,
                                                        role_identities_history=self.history))
        self.result = {"name": "冰心诀", "kungfu_id": 10081, "season_id": "season-a",
                       "season_start": 1000, "pvp_type": 3, "algorithm_version": 1,
                       "source": "indicator", "requested_at": 1900.0, "verified_at": 1901.0,
                       "win_sample_count": 0, "publish_version": 1}

    async def publish(self, generation=1, locator=None, result=None):
        method = getattr(self.repo, "publish_jjc_kungfu_if_newer", None)
        self.assertTrue(callable(method), "narrow role kungfu publication method is required")
        return await method(self.identity_id, self.locator if locator is None else locator,
                            generation, self.result if result is None else result)

    async def test_publication_changes_only_kungfu_and_does_not_archive_or_touch_identity_clock(self):
        self.assertTrue(await self.publish())
        expected = dict(self.before, jjc_kungfu=self.result)
        self.assertEqual(self.collection.doc, expected)
        self.history.insert_one.assert_not_awaited()
        query, update = self.collection.update_one.call_args.args[:2]
        self.assertNotIn("updated_at", query)
        self.assertEqual(update, {"$set": {"jjc_kungfu": self.result}})
        self.assertFalse(self.collection.update_one.call_args.kwargs.get("upsert", False))

    async def test_old_or_same_version_cannot_overwrite_success(self):
        self.collection.doc["jjc_kungfu"] = dict(self.result, publish_version=2, name="云裳心经")
        before = copy.deepcopy(self.collection.doc)
        self.assertFalse(await self.publish())
        self.assertEqual(self.collection.doc, before)
        self.result["publish_version"] = 2
        self.assertFalse(await self.publish(generation=2))
        self.assertEqual(self.collection.doc, before)

    async def test_higher_version_can_replace_different_season_success(self):
        self.collection.doc["jjc_kungfu"] = dict(self.result, season_id="old-season", publish_version=1)
        self.result["publish_version"] = 2
        self.assertTrue(await self.publish(generation=2))
        self.assertEqual(self.collection.doc["jjc_kungfu"], self.result)

    async def test_locator_change_during_query_rejects_publication(self):
        for field in self.locator:
            with self.subTest(field=field):
                self.collection.doc = dict(self.before, **{field: "changed"})
                self.assertFalse(await self.publish())
                self.assertNotIn("jjc_kungfu", self.collection.doc)

    async def test_missing_identity_is_not_recreated(self):
        self.collection.doc = None
        self.assertFalse(await self.publish())
        self.assertIsNone(self.collection.doc)

    async def test_malformed_existing_subobject_is_not_automatically_overwritten(self):
        for previous in (None, {}, {"publish_version": "0"}, {"publish_version": True},
                         {"publish_version": -1}, {"publish_version": 1.5}):
            with self.subTest(previous=previous):
                self.collection.doc = dict(self.before, jjc_kungfu=copy.deepcopy(previous))
                self.assertFalse(await self.publish())
                self.assertEqual(self.collection.doc["jjc_kungfu"], previous)

    async def test_result_version_must_match_claimed_generation(self):
        try:
            actual = await self.publish(generation=2)
        except ValueError:
            actual = False
        self.assertFalse(actual)
        self.collection.update_one.assert_not_awaited()

    async def test_null_and_missing_locator_values_are_distinct(self):
        locator = dict(self.locator, global_role_id=None)
        self.assertFalse(await self.publish(locator=locator))
        self.collection.doc["global_role_id"] = None
        self.assertTrue(await self.publish(locator=locator))

    async def test_successful_kungfu_change_does_not_invalidate_existing_identity_snapshot_cas(self):
        identity_cas = _snapshot_filter(self.before)
        self.assertTrue(await self.publish())
        self.assertTrue(matches(self.collection.doc, identity_cas))
