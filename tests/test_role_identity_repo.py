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

    def find(self, query: Dict[str, Any]) -> AsyncListCursor:
        return AsyncListCursor([])


class FakeDb:
    def __init__(self) -> None:
        self.role_identities = FakeCollection()
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
        self.assertEqual(update["$addToSet"]["profile_history"]["source"], "match_detail")

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
        self.assertEqual(result["profile_history"][0]["global_id"], "99999")

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
        self.assertEqual(result["profile_history"][0]["person_id"], "person-a")
        inserted = db.role_identities.insert_one.call_args.args[0]
        self.assertEqual(inserted["person_id"], "person-a")

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
        self.assertEqual(update["$addToSet"]["profile_history"]["person_id"], "person-a")

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


if __name__ == "__main__":
    unittest.main()
