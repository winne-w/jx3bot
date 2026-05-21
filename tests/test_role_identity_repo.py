import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

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
        self.assertEqual(update["$set"]["global_role_id"], "gid")
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

    async def test_ranking_can_update_current_server_name(self) -> None:
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
        self.assertEqual(update["$set"]["server"], "新服")
        self.assertEqual(update["$set"]["name"], "新名")
        self.assertEqual(update["$set"]["normalized_server"], "新服")
        self.assertEqual(update["$set"]["normalized_name"], "新名")
        self.assertIn("profile_observed_at", update["$set"])

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


if __name__ == "__main__":
    unittest.main()
