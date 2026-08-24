import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

from bson import ObjectId

from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo


class AsyncListCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: Any) -> List[Dict[str, Any]]:
        return self._docs


class FakeCollection:
    def __init__(self) -> None:
        self.find_one = AsyncMock(return_value=None)
        self.update_one = AsyncMock(return_value=SimpleNamespace(matched_count=1))
        self.insert_one = AsyncMock(return_value=SimpleNamespace(inserted_id="id"))

    def find(self, query: Dict[str, Any], projection: Any = None) -> AsyncListCursor:
        return AsyncListCursor([])


class FakeDb:
    def __init__(self) -> None:
        self.role_identities = FakeCollection()
        self.role_identities_history = FakeCollection()


class AggregateListCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs

    async def to_list(self, length: Any) -> List[Dict[str, Any]]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class CandidateCollection:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self.docs = docs
        self.pipeline: List[Dict[str, Any]] = []

    def find(self, query: Dict[str, Any], projection: Any = None) -> AsyncListCursor:
        raise AssertionError("candidate lookup must use aggregate")

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> AggregateListCursor:
        self.pipeline = pipeline
        match_stage = pipeline[0]["$match"]["$or"]
        exact_name = match_stage[0]["normalized_name"]
        excluded_server = match_stage[0]["normalized_server"]["$ne"]
        suffix_pattern = match_stage[1]["normalized_name"]["$regex"]
        suffix_prefix = suffix_pattern[1:].replace("\\@", "@")
        limit = next(stage["$limit"] for stage in pipeline if "$limit" in stage)

        def identity_strength(doc: Dict[str, Any]) -> int:
            level = doc.get("identity_level")
            if level == "global_id" or doc.get("global_id"):
                return 3
            if level == "global" or doc.get("global_role_id"):
                return 2
            if level == "game_role" or doc.get("game_role_id") or doc.get("role_id"):
                return 1
            return 0

        def timestamp_value(value: Any) -> float:
            if isinstance(value, datetime):
                return value.timestamp()
            if isinstance(value, (int, float)):
                return float(value)
            return 0.0

        def normalize(value: Any) -> str:
            return str(value or "").strip().lower()

        def candidate_role_key(doc: Dict[str, Any]) -> tuple:
            server = doc.get("normalized_server") or doc.get("server")
            name = doc.get("normalized_name") or doc.get("name")
            return (normalize(server), normalize(name))

        def decorate_candidate(doc: Dict[str, Any]) -> None:
            doc["_candidate_same_server"] = 1 if doc.get("normalized_server") == excluded_server else 0
            doc["_candidate_identity_strength"] = identity_strength(doc)
            doc["_candidate_freshness"] = max(
                timestamp_value(doc.get("last_seen_at")),
                timestamp_value(doc.get("updated_at")),
            )
            role_server, role_name = candidate_role_key(doc)
            doc["_candidate_role_server"] = role_server
            doc["_candidate_role_name"] = role_name

        def sort_value(value: Any) -> Any:
            if isinstance(value, datetime):
                return value.timestamp()
            return value

        def apply_sort(docs: List[Dict[str, Any]], spec: Dict[str, int]) -> None:
            for field, direction in reversed(list(spec.items())):
                docs.sort(
                    key=lambda doc: sort_value(doc.get(field)),
                    reverse=direction < 0,
                )

        matched = []
        for doc in self.docs:
            normalized_name = doc.get("normalized_name")
            normalized_server = doc.get("normalized_server")
            if (
                normalized_name == exact_name
                and normalized_server != excluded_server
            ) or (
                isinstance(normalized_name, str)
                and normalized_name.startswith(suffix_prefix)
            ):
                candidate = dict(doc)
                decorate_candidate(candidate)
                matched.append(candidate)

        first_sort = next(stage["$sort"] for stage in pipeline if "$sort" in stage)
        apply_sort(matched, first_sort)

        grouped = []
        seen_role_keys = set()
        for doc in matched:
            role_key = (doc["_candidate_role_server"], doc["_candidate_role_name"])
            if role_key in seen_role_keys:
                continue
            seen_role_keys.add(role_key)
            grouped.append(doc)

        # Mongo $group output order is explicitly unspecified; make the fake
        # aggregate hostile so tests fail without a post-group deterministic sort.
        grouped.reverse()

        replace_root_index = next(
            index for index, stage in enumerate(pipeline) if "$replaceRoot" in stage
        )
        limit_index = next(index for index, stage in enumerate(pipeline) if "$limit" in stage)
        final_sort = next(
            (
                stage["$sort"]
                for stage in pipeline[replace_root_index + 1:limit_index]
                if "$sort" in stage
            ),
            None,
        )
        if final_sort is not None:
            apply_sort(grouped, final_sort)

        for doc in grouped:
            doc.pop("_candidate_same_server", None)
            doc.pop("_candidate_identity_strength", None)
            doc.pop("_candidate_freshness", None)
            doc.pop("_candidate_role_server", None)
            doc.pop("_candidate_role_name", None)
        return AggregateListCursor(grouped[:limit])


class CandidateDb:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self.role_identities = CandidateCollection(docs)
        self.role_identities_history = FakeCollection()


class TestRoleIdentityRepo(unittest.IsolatedAsyncioTestCase):
    async def test_match_detail_does_not_overwrite_existing_current_server_name(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global:gid",
            "identity_level": "global",
            "server": "新服",
            "normalized_server": "新服",
            "name": "新名",
            "normalized_name": "新名",
            "global_role_id": "gid",
            "profile_observed_at": datetime(2026, 5, 6, tzinfo=timezone.utc),
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail(
            server="老服",
            name="旧名",
            global_role_id="gid",
            role_id="rid",
            observed_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
        )

        _, update = db.role_identities.update_one.call_args.args
        self.assertNotIn("server", update["$set"])
        self.assertNotIn("name", update["$set"])
        self.assertNotIn("global_role_id", update["$set"])
        self.assertEqual(update["$set"]["role_id"], "rid")
        self.assertEqual(update["$addToSet"]["sources"], "match_detail")
        self.assertNotIn("profile_history", update["$addToSet"])

    async def test_match_detail_overwrites_profile_when_match_time_is_newer(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global:gid",
            "identity_level": "global",
            "server": "旧服",
            "normalized_server": "旧服",
            "name": "旧名",
            "normalized_name": "旧名",
            "global_role_id": "gid",
            "profile_observed_at": datetime(2026, 5, 6, tzinfo=timezone.utc),
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail(
            server="新服",
            name="新名",
            global_role_id="gid",
            role_id="rid",
            observed_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        )

        _, update = db.role_identities.update_one.call_args.args
        self.assertEqual(update["$set"]["server"], "新服")
        self.assertEqual(update["$set"]["name"], "新名")
        self.assertEqual(
            update["$set"]["profile_observed_at"],
            datetime(2026, 5, 7, tzinfo=timezone.utc),
        )

    async def test_ranking_only_fills_missing_profile_fields(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global:gid",
            "identity_level": "global",
            "server": "老服",
            "normalized_server": "老服",
            "name": "旧名",
            "normalized_name": "旧名",
            "global_role_id": "gid",
            "profile_observed_at": datetime(2026, 5, 5, tzinfo=timezone.utc),
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_ranking(
            server="新服",
            name="新名",
            zone="zone-a",
            game_role_id="rid",
            global_role_id="gid",
        )

        _, update = db.role_identities.update_one.call_args.args
        self.assertNotIn("server", update["$set"])
        self.assertNotIn("name", update["$set"])
        self.assertEqual(update["$set"]["zone"], "zone-a")
        self.assertEqual(update["$set"]["game_role_id"], "rid")
        self.assertNotIn("profile_observed_at", update["$set"])

    async def test_old_match_detail_does_not_overwrite_existing_role_id(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global_id:99999",
            "identity_level": "global_id",
            "server": "新服",
            "normalized_server": "新服",
            "name": "新名",
            "normalized_name": "新名",
            "global_id": "99999",
            "global_role_id": "SK01-new",
            "role_id": "rid-new",
            "game_role_id": "rid-new",
            "role_info_observed_match_time": 1810000100,
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail(
            server="老服",
            name="旧名",
            global_id="99999",
            global_role_id="SK01-old",
            role_id="rid-old",
            observed_match_time=1810000000,
        )

        _, update = db.role_identities.update_one.call_args.args
        self.assertNotIn("role_id", update["$set"])
        self.assertNotIn("game_role_id", update["$set"])
        self.assertNotIn("global_role_id", update["$set"])
        self.assertNotIn("role_info_observed_match_time", update["$set"])

    async def test_newer_match_detail_overwrites_existing_role_id(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global_id:99999",
            "identity_level": "global_id",
            "server": "旧服",
            "normalized_server": "旧服",
            "name": "旧名",
            "normalized_name": "旧名",
            "global_id": "99999",
            "global_role_id": "SK01-old",
            "role_id": "rid-old",
            "game_role_id": "rid-old",
            "role_info_observed_match_time": 1810000000,
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail(
            server="新服",
            name="新名",
            global_id="99999",
            global_role_id="SK01-new",
            role_id="rid-new",
            observed_match_time=1810000100,
        )

        _, update = db.role_identities.update_one.call_args.args
        self.assertEqual(update["$set"]["role_id"], "rid-new")
        self.assertEqual(update["$set"]["game_role_id"], "rid-new")
        self.assertEqual(update["$set"]["global_role_id"], "SK01-new")
        self.assertEqual(update["$set"]["role_info_observed_match_time"], 1810000100)
        archived = db.role_identities_history.insert_one.call_args.args[0]
        self.assertEqual(archived["identity_key"], "global_id:99999")
        self.assertEqual(archived["server"], "旧服")
        self.assertEqual(archived["name"], "旧名")
        self.assertEqual(archived["global_role_id"], "SK01-old")
        self.assertEqual(archived["archive_reason"], "role_identity_profile_updated")
        self.assertEqual(archived["replaced_by_identity_key"], "global_id:99999")

    async def test_newer_match_detail_role_id_only_change_does_not_archive(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global_id:99999",
            "identity_level": "global_id",
            "server": "梦江南",
            "normalized_server": "梦江南",
            "name": "角色A",
            "normalized_name": "角色A",
            "global_id": "99999",
            "global_role_id": "SK01-same",
            "role_id": "rid-old",
            "game_role_id": "rid-old",
            "role_info_observed_match_time": 1810000000,
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail(
            server="梦江南",
            name="角色A",
            global_id="99999",
            global_role_id="SK01-same",
            role_id="rid-new",
            observed_match_time=1810000100,
        )

        db.role_identities_history.insert_one.assert_not_called()

    async def test_profile_archive_failure_prevents_overwrite(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global_id:99999",
            "identity_level": "global_id",
            "server": "旧服",
            "normalized_server": "旧服",
            "name": "旧名",
            "normalized_name": "旧名",
            "global_id": "99999",
            "global_role_id": "SK01-old",
            "role_info_observed_match_time": 1810000000,
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
        ]
        db.role_identities_history.insert_one.side_effect = RuntimeError("archive down")
        repo = RoleIdentityRepo(db=db)

        result = await repo.upsert_from_match_detail(
            server="新服",
            name="新名",
            global_id="99999",
            global_role_id="SK01-new",
            observed_match_time=1810000100,
        )

        self.assertEqual(result["server"], "旧服")
        db.role_identities.update_one.assert_not_called()

    async def test_legacy_upgrade_does_not_overwrite_profile_with_old_match(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global:SK01-abc",
            "identity_level": "global",
            "server": "新服",
            "normalized_server": "新服",
            "name": "新名",
            "normalized_name": "新名",
            "global_role_id": "SK01-abc",
            "role_id": "rid-new",
            "game_role_id": "rid-new",
            "role_info_observed_match_time": 1810000100,
        }
        db.role_identities.find_one.side_effect = [
            None,
            dict(existing),
            dict(existing, identity_key="global_id:99999", identity_level="global_id", global_id="99999"),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail(
            server="老服",
            name="旧名",
            zone="电信区",
            game_role_id="rid-old",
            global_role_id="SK01-abc",
            global_id="99999",
            role_id="rid-old",
            observed_match_time=1810000000,
        )

        _, update = db.role_identities.update_one.call_args.args
        self.assertEqual(update["$set"]["identity_key"], "global_id:99999")
        self.assertEqual(update["$set"]["identity_level"], "global_id")
        self.assertEqual(update["$set"]["global_id"], "99999")
        self.assertNotIn("server", update["$set"])
        self.assertNotIn("name", update["$set"])
        self.assertNotIn("role_id", update["$set"])
        self.assertNotIn("game_role_id", update["$set"])

    async def test_global_id_is_preferred_over_sk01_global_role_id(self) -> None:
        db = FakeDb()
        repo = RoleIdentityRepo(db=db)

        result = await repo.upsert_from_match_detail(
            server="梦江南",
            name="角色A",
            zone="电信区",
            game_role_id="rid-a",
            global_role_id="SK01-abc",
            global_id="99999",
            role_id="rid-a",
            person_id="person-a",
        )

        self.assertEqual(result["identity_key"], "global_id:99999")
        self.assertEqual(result["identity_level"], "global_id")
        self.assertEqual(result["global_id"], "99999")
        self.assertEqual(result["global_role_id"], "SK01-abc")
        self.assertNotIn("profile_history", result)

    async def test_indicator_new_identity_writes_person_id(self) -> None:
        db = FakeDb()
        repo = RoleIdentityRepo(db=db)

        result = await repo.upsert_from_indicator(
            server="梦江南",
            name="角色A",
            zone="电信区",
            game_role_id="rid-a",
            global_role_id="SK01-abc",
            role_id="rid-a",
            person_id="person-a",
        )

        self.assertEqual(result["person_id"], "person-a")
        self.assertNotIn("profile_history", result)
        inserted = db.role_identities.insert_one.call_args.args[0]
        self.assertEqual(inserted["person_id"], "person-a")
        self.assertNotIn("profile_history", inserted)

    async def test_indicator_fills_missing_person_id_on_existing_identity(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global:SK01-abc",
            "identity_level": "global",
            "server": "梦江南",
            "normalized_server": "梦江南",
            "name": "角色A",
            "normalized_name": "角色A",
            "global_role_id": "SK01-abc",
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing, person_id="person-a"),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_indicator(
            server="梦江南",
            name="角色A",
            zone="电信区",
            game_role_id="rid-a",
            global_role_id="SK01-abc",
            role_id="rid-a",
            person_id="person-a",
        )

        _, update = db.role_identities.update_one.call_args.args
        self.assertEqual(update["$set"]["person_id"], "person-a")
        self.assertNotIn("profile_history", update["$addToSet"])

    async def test_legacy_global_role_identity_upgrades_to_global_id(self) -> None:
        db = FakeDb()
        existing = {
            "identity_key": "global:SK01-abc",
            "identity_level": "global",
            "server": "梦江南",
            "normalized_server": "梦江南",
            "name": "角色A",
            "normalized_name": "角色A",
            "global_role_id": "SK01-abc",
        }
        db.role_identities.find_one.side_effect = [
            None,
            dict(existing),
            dict(existing, identity_key="global_id:99999", identity_level="global_id", global_id="99999"),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail(
            server="梦江南",
            name="角色A",
            zone="电信区",
            game_role_id="rid-a",
            global_role_id="SK01-abc",
            global_id="99999",
        )

        filter_doc, update = db.role_identities.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "global:SK01-abc"})
        self.assertEqual(update["$set"]["identity_key"], "global_id:99999")
        self.assertEqual(update["$set"]["identity_level"], "global_id")
        self.assertEqual(update["$set"]["global_id"], "99999")
        self.assertIn("global:SK01-abc", update["$addToSet"]["aliases"]["$each"])

    async def test_resolve_best_identity_strips_id_but_with_id_preserves_id(self) -> None:
        identity_id = ObjectId()
        db = FakeDb()
        db.role_identities.find_one.side_effect = [
            {"_id": identity_id, "identity_key": "global:gid", "global_role_id": "gid"},
            {"_id": identity_id, "identity_key": "global:gid", "global_role_id": "gid"},
        ]
        repo = RoleIdentityRepo(db=db)

        legacy = await repo.resolve_best_identity(
            server="梦江南",
            name="角色A",
            global_role_id="gid",
        )
        with_id = await repo.resolve_best_identity_with_id(
            server="梦江南",
            name="角色A",
            global_role_id="gid",
        )

        self.assertNotIn("_id", legacy)
        self.assertEqual(with_id["_id"], identity_id)

    async def test_global_id_lookup_includes_partial_index_type_filter(self) -> None:
        identity_id = ObjectId()
        db = FakeDb()
        db.role_identities.find_one.side_effect = [
            {"_id": identity_id, "identity_key": "global_id:gid", "global_id": "gid"},
            {"_id": identity_id, "identity_key": "global_id:gid", "global_id": "gid"},
        ]
        repo = RoleIdentityRepo(db=db)

        legacy = await repo.find_by_global_id("gid")
        with_id = await repo.resolve_best_identity_with_id(
            server="梦江南",
            name="角色A",
            global_id="gid",
        )

        self.assertNotIn("_id", legacy)
        self.assertEqual(with_id["_id"], identity_id)
        find_by_global_id_query = db.role_identities.find_one.call_args_list[0].args[0]
        resolve_query = db.role_identities.find_one.call_args_list[1].args[0]
        expected_global_id_filter = {"global_id": {"$eq": "gid", "$type": "string"}}
        self.assertIn(expected_global_id_filter, find_by_global_id_query["$or"])
        self.assertIn(expected_global_id_filter, resolve_query["$or"])

    async def test_upsert_from_match_detail_with_id_preserves_existing_id(self) -> None:
        identity_id = ObjectId()
        db = FakeDb()
        existing = {
            "_id": identity_id,
            "identity_key": "global:gid",
            "identity_level": "global",
            "server": "梦江南",
            "normalized_server": "梦江南",
            "name": "角色A",
            "normalized_name": "角色A",
            "global_role_id": "gid",
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing, role_id="rid"),
        ]
        repo = RoleIdentityRepo(db=db)

        result = await repo.upsert_from_match_detail_with_id(
            server="梦江南",
            name="角色A",
            global_role_id="gid",
            role_id="rid",
        )

        self.assertEqual(result["_id"], identity_id)

    async def test_match_detail_with_id_uses_slim_projection_for_lookup_and_reload(self) -> None:
        identity_id = ObjectId()
        db = FakeDb()
        existing = {
            "_id": identity_id,
            "identity_key": "global_id:gid-a",
            "identity_level": "global_id",
            "server": "梦江南",
            "normalized_server": "梦江南",
            "name": "角色A",
            "normalized_name": "角色a",
            "global_id": "gid-a",
        }
        db.role_identities.find_one.side_effect = [
            dict(existing),
            dict(existing, role_id="rid-a"),
        ]
        repo = RoleIdentityRepo(db=db)

        await repo.upsert_from_match_detail_with_id(
            server="梦江南",
            name="角色A",
            global_id="gid-a",
            role_id="rid-a",
        )

        lookup_call = db.role_identities.find_one.call_args_list[0]
        reload_call = db.role_identities.find_one.call_args_list[1]
        self.assertEqual(lookup_call.args[1]["profile_observed_at"], 1)
        self.assertEqual(reload_call.args[1]["role_info_observed_match_time"], 1)
        self.assertNotIn("profile_history", lookup_call.args[1])
        self.assertNotIn("profile_history", reload_call.args[1])

    async def test_refresh_indicator_fields_by_id_updates_expected_fields(self) -> None:
        identity_id = ObjectId()
        db = FakeDb()
        db.role_identities.find_one.return_value = {
            "_id": identity_id,
            "identity_key": "global:gid-new",
            "global_role_id": "gid-new",
        }
        repo = RoleIdentityRepo(db=db)

        result = await repo.refresh_indicator_fields_by_id(
            str(identity_id),
            global_role_id="gid-new",
            refresh_source="indicator_api",
            zone="电信区",
            game_role_id="game-rid",
            role_id="role-rid",
            person_id="person-a",
            server="梦江南",
            name="角色A",
        )

        filter_doc, update = db.role_identities.update_one.call_args.args
        self.assertEqual(filter_doc, {"_id": identity_id})
        self.assertEqual(update["$set"]["global_role_id"], "gid-new")
        self.assertIn("global_role_id_refreshed_at", update["$set"])
        self.assertEqual(update["$set"]["global_role_id_refresh_source"], "indicator_api")
        self.assertEqual(update["$set"]["zone"], "电信区")
        self.assertEqual(update["$set"]["game_role_id"], "game-rid")
        self.assertEqual(update["$set"]["role_id"], "role-rid")
        self.assertEqual(update["$set"]["person_id"], "person-a")
        self.assertEqual(update["$set"]["normalized_server"], "梦江南")
        self.assertEqual(update["$set"]["normalized_name"], "角色a")
        self.assertEqual(result["_id"], identity_id)

    async def test_synced_match_page_candidates_empty_name_returns_empty_list(self) -> None:
        db = CandidateDb([])
        repo = RoleIdentityRepo(db=db)

        result = await repo.find_synced_match_page_candidates(server="梦江南", name="  ")

        self.assertEqual(result, [])
        self.assertEqual(db.role_identities.pipeline, [])

    async def test_synced_match_page_candidates_empty_server_means_all_servers(self) -> None:
        docs = [
            {
                "_id": "same-name-a",
                "identity_key": "global_id:a",
                "identity_level": "global_id",
                "server": "梦江南",
                "normalized_server": "梦江南",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "same-name-b",
                "identity_key": "global:b",
                "identity_level": "global",
                "server": "唯我独尊",
                "normalized_server": "唯我独尊",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "suffix",
                "identity_key": "game:suffix",
                "identity_level": "game_role",
                "server": "长安城",
                "normalized_server": "长安城",
                "name": "角色A@旧服",
                "normalized_name": "角色a@旧服",
                "last_seen_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
            },
        ]
        db = CandidateDb(docs)
        repo = RoleIdentityRepo(db=db)

        result = await repo.find_synced_match_page_candidates(
            server="",
            name="角色A",
            limit=8,
        )

        self.assertEqual(
            [doc["identity_key"] for doc in result],
            ["global_id:a", "global:b", "game:suffix"],
        )
        self.assertEqual(
            db.role_identities.pipeline[0]["$match"]["$or"][0]["normalized_server"]["$ne"],
            "",
        )

    async def test_synced_match_page_candidates_include_suffixes_and_sort_deterministically(self) -> None:
        docs = [
            {
                "_id": "exact-same-server",
                "identity_key": "global_id:exact",
                "identity_level": "global_id",
                "server": "梦江南",
                "normalized_server": "梦江南",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "other-global-old",
                "identity_key": "global:old",
                "identity_level": "global",
                "server": "唯我独尊",
                "normalized_server": "唯我独尊",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "other-global-new",
                "identity_key": "global:new",
                "identity_level": "global",
                "server": "长安城",
                "normalized_server": "长安城",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "other-game-fresh",
                "identity_key": "game:fresh",
                "identity_level": "game_role",
                "server": "乾坤一掷",
                "normalized_server": "乾坤一掷",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "same-server-suffix",
                "identity_key": "name:suffix",
                "identity_level": "name",
                "server": "梦江南",
                "normalized_server": "梦江南",
                "name": "角色A@旧服",
                "normalized_name": "角色a@旧服",
                "last_seen_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "other-server-suffix",
                "identity_key": "global_id:suffix",
                "identity_level": "global_id",
                "server": "姨妈服",
                "normalized_server": "姨妈服",
                "name": "角色A@梦江南",
                "normalized_name": "角色a@梦江南",
                "last_seen_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
            {
                "_id": "unrelated",
                "identity_key": "global_id:unrelated",
                "identity_level": "global_id",
                "server": "梦江南",
                "normalized_server": "梦江南",
                "name": "其他角色",
                "normalized_name": "其他角色",
                "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            },
        ]
        db = CandidateDb(docs)
        repo = RoleIdentityRepo(db=db)

        result = await repo.find_synced_match_page_candidates(
            server="梦江南",
            name=" 角色A ",
            limit=5,
        )

        self.assertEqual(
            [doc["identity_key"] for doc in result],
            [
                "name:suffix",
                "global_id:suffix",
                "global:new",
                "global:old",
                "game:fresh",
            ],
        )
        self.assertNotIn("global_id:exact", [doc["identity_key"] for doc in result])
        self.assertEqual(db.role_identities.pipeline[0]["$match"]["$or"][0]["normalized_name"], "角色a")
        stage_names = [next(iter(stage.keys())) for stage in db.role_identities.pipeline]
        replace_root_index = stage_names.index("$replaceRoot")
        limit_index = stage_names.index("$limit")
        final_sort_indexes = [
            index
            for index, stage_name in enumerate(stage_names)
            if stage_name == "$sort" and replace_root_index < index < limit_index
        ]
        self.assertEqual(len(final_sort_indexes), 1)
        final_sort = db.role_identities.pipeline[final_sort_indexes[0]]["$sort"]
        self.assertIn("_candidate_same_server", final_sort)
        self.assertIn("_candidate_identity_strength", final_sort)
        self.assertIn("_candidate_freshness", final_sort)
        self.assertIn("_candidate_role_server", final_sort)
        self.assertIn("_candidate_role_name", final_sort)
        project_index = stage_names.index("$project")
        self.assertGreater(project_index, final_sort_indexes[0])

    async def test_synced_match_page_candidates_dedupe_same_server_name_keeps_best(self) -> None:
        docs = [
            {
                "_id": "dup-weaker-fresher",
                "identity_key": "name:duplicate",
                "identity_level": "name",
                "server": "长安城",
                "normalized_server": "长安城",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 10, tzinfo=timezone.utc),
            },
            {
                "_id": "dup-best",
                "identity_key": "global_id:duplicate",
                "identity_level": "global_id",
                "server": "长安城",
                "normalized_server": "长安城",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "unique-a",
                "identity_key": "global:unique-a",
                "identity_level": "global",
                "server": "乾坤一掷",
                "normalized_server": "乾坤一掷",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "unique-b",
                "identity_key": "global:unique-b",
                "identity_level": "global",
                "server": "唯我独尊",
                "normalized_server": "唯我独尊",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            },
        ]
        db = CandidateDb(docs)
        repo = RoleIdentityRepo(db=db)

        result = await repo.find_synced_match_page_candidates(
            server="梦江南",
            name="角色A",
            limit=3,
        )

        self.assertEqual(
            [doc["identity_key"] for doc in result],
            ["global_id:duplicate", "global:unique-a", "global:unique-b"],
        )
        self.assertNotIn("name:duplicate", [doc["identity_key"] for doc in result])

    async def test_synced_match_page_candidates_groups_before_limit(self) -> None:
        docs = []
        for index in range(7):
            docs.append({
                "_id": f"dup-{index}",
                "identity_key": f"global_id:duplicate-{index}",
                "identity_level": "global_id",
                "server": "长安城",
                "normalized_server": "长安城",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 10 - index, tzinfo=timezone.utc),
            })
        docs.append({
            "_id": "later-unique",
            "identity_key": "global:later-unique",
            "identity_level": "global",
            "server": "乾坤一掷",
            "normalized_server": "乾坤一掷",
            "name": "角色A",
            "normalized_name": "角色a",
            "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        })
        db = CandidateDb(docs)
        repo = RoleIdentityRepo(db=db)

        result = await repo.find_synced_match_page_candidates(
            server="梦江南",
            name="角色A",
            limit=3,
        )

        self.assertEqual(
            [doc["identity_key"] for doc in result],
            ["global_id:duplicate-0", "global:later-unique"],
        )
        stage_names = [next(iter(stage.keys())) for stage in db.role_identities.pipeline]
        self.assertLess(stage_names.index("$sort"), stage_names.index("$group"))
        self.assertLess(stage_names.index("$group"), stage_names.index("$limit"))
        replace_root_index = stage_names.index("$replaceRoot")
        limit_index = stage_names.index("$limit")
        self.assertTrue(
            any(
                stage_name == "$sort" and replace_root_index < index < limit_index
                for index, stage_name in enumerate(stage_names)
            )
        )

    async def test_candidate_collection_sort_matches_mixed_mongo_directions(self) -> None:
        docs = [
            {
                "_id": "server-z",
                "identity_key": "global:z",
                "identity_level": "global",
                "server": "Z服",
                "normalized_server": "z服",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            },
            {
                "_id": "server-a",
                "identity_key": "global:a",
                "identity_level": "global",
                "server": "A服",
                "normalized_server": "a服",
                "name": "角色A",
                "normalized_name": "角色a",
                "last_seen_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            },
        ]
        db = CandidateDb(docs)
        repo = RoleIdentityRepo(db=db)

        result = await repo.find_synced_match_page_candidates(
            server="梦江南",
            name="角色A",
            limit=2,
        )

        self.assertEqual([doc["identity_key"] for doc in result], ["global:a", "global:z"])


if __name__ == "__main__":
    unittest.main()
