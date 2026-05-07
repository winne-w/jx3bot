import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

from pymongo.errors import DuplicateKeyError

from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo


class FakeCollection:
    def __init__(self) -> None:
        self.find_one = AsyncMock(return_value=None)
        self.insert_one = AsyncMock(return_value=SimpleNamespace(inserted_id="id"))
        self.update_one = AsyncMock(
            return_value=SimpleNamespace(
                matched_count=1,
                modified_count=1,
                upserted_id=None,
            )
        )
        self.update_many = AsyncMock(return_value=SimpleNamespace(modified_count=0))
        self.find_one_and_update = AsyncMock(return_value=None)
        self.aggregate_calls: List[Any] = []

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> Any:
        self.aggregate_calls.append(pipeline)
        return AsyncListCursor([])


class AsyncListCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs

    def __aiter__(self) -> "AsyncListCursor":
        self._iter = iter(self._docs)
        return self

    async def __anext__(self) -> Dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeDb:
    def __init__(self) -> None:
        self.jjc_sync_role_queue = FakeCollection()
        self.jjc_sync_match_seen = FakeCollection()
        self.jjc_sync_state = FakeCollection()


class TestJjcSyncRepoIdentity(unittest.TestCase):
    def test_identity_key_priority(self) -> None:
        self.assertEqual(
            JjcSyncRepo._build_identity_key(
                global_role_id="gid",
                zone="z",
                role_id="rid",
                normalized_server="s",
                normalized_name="n",
            ),
            "global:gid",
        )
        self.assertEqual(
            JjcSyncRepo._build_identity_key(
                zone="z",
                role_id="rid",
                normalized_server="s",
                normalized_name="n",
            ),
            "game:z:rid",
        )
        self.assertEqual(
            JjcSyncRepo._build_identity_key(normalized_server="s", normalized_name="n"),
            "name:s:n",
        )


class TestJjcSyncRepoRoleQueue(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_existing_role_does_not_reset_waterline(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "global:gid",
            "full_synced_until_time": 1000,
            "history_exhausted": True,
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="gid",
            source="match_detail",
            priority=-10,
            season_id="s1",
            season_start_time=123,
        )

        self.assertEqual(result, "global:gid")
        db.jjc_sync_role_queue.insert_one.assert_not_called()
        _, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertNotIn("full_synced_until_time", update["$set"])
        self.assertNotIn("history_exhausted", update["$set"])
        self.assertNotIn("source", update["$set"])
        self.assertEqual(update["$max"], {"priority": -10})

    async def test_duplicate_insert_falls_back_to_update(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.insert_one.side_effect = DuplicateKeyError("dup")
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="gid",
            source="manual",
        )

        self.assertEqual(result, "global:gid")
        db.jjc_sync_role_queue.update_one.assert_called_once()
        _, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(update["$set"]["source"], "manual")

    async def test_release_role_failure_third_failure_marks_failed(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {"fail_count": 2}
        repo = JjcSyncRepo(db=db)

        await repo.release_role_failure("global:gid", "boom")

        _, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(update["$set"]["status"], "failed")
        self.assertEqual(update["$set"]["fail_count"], 3)
        self.assertEqual(update["$set"]["last_error"], "boom")
        self.assertIsNone(update["$set"]["lease_owner"])

    async def test_update_role_identity_fields_does_not_change_waterline(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.update_role_identity_fields(
            identity_key="name:梦江南:角色A",
            global_role_id="gid",
            role_id="rid",
            zone="zone-a",
            identity_source="role_identity_name_match",
        )

        self.assertTrue(result)
        filter_doc, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "name:梦江南:角色A"})
        self.assertEqual(update["$set"]["global_role_id"], "gid")
        self.assertEqual(update["$set"]["role_id"], "rid")
        self.assertEqual(update["$set"]["zone"], "zone-a")
        self.assertEqual(update["$set"]["identity_source"], "role_identity_name_match")
        self.assertNotIn("full_synced_until_time", update["$set"])

    async def test_recover_expired_leases_updates_role_and_match(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.update_many.return_value = SimpleNamespace(modified_count=2)
        db.jjc_sync_match_seen.update_many.return_value = SimpleNamespace(modified_count=3)
        repo = JjcSyncRepo(db=db)

        recovered = await repo.recover_expired_leases()

        self.assertEqual(recovered, 5)
        role_filter = db.jjc_sync_role_queue.update_many.call_args.kwargs["filter"]
        role_update = db.jjc_sync_role_queue.update_many.call_args.kwargs["update"]
        self.assertEqual(role_filter["status"], "syncing")
        self.assertEqual(role_update["$set"]["status"], "pending")
        match_filter = db.jjc_sync_match_seen.update_many.call_args.kwargs["filter"]
        match_update = db.jjc_sync_match_seen.update_many.call_args.kwargs["update"]
        self.assertEqual(match_filter["status"], "detail_syncing")
        self.assertEqual(match_update["$set"]["status"], "discovered")

    async def test_claim_next_roles_includes_due_cooldown_and_exhausted(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one_and_update.return_value = {
            "identity_key": "global:gid",
            "status": "syncing",
        }
        repo = JjcSyncRepo(db=db)

        claimed = await repo.claim_next_roles(limit=1, lease_owner="owner", lease_seconds=60)

        self.assertEqual(len(claimed), 1)
        filter_doc = db.jjc_sync_role_queue.find_one_and_update.call_args.kwargs["filter"]
        self.assertEqual(
            filter_doc["status"],
            {"$in": ["pending", "cooldown", "exhausted"]},
        )


class TestJjcSyncRepoMatchSeen(unittest.IsolatedAsyncioTestCase):
    async def test_mark_match_discovered_uses_set_on_insert_and_upsert(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.update_one.return_value = SimpleNamespace(upserted_id="new-id")
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_discovered(
            match_id="1001",
            match_time=1810000000,
            source_identity_key="global:gid",
            source_server="梦江南",
            source_role_name="角色A",
        )

        self.assertTrue(result)
        call = db.jjc_sync_match_seen.update_one.call_args
        self.assertEqual(call.args[0], {"match_id": 1001})
        self.assertTrue(call.kwargs["upsert"])
        self.assertEqual(call.args[1]["$setOnInsert"]["status"], "discovered")
        self.assertEqual(call.args[1]["$setOnInsert"]["source_identity_key"], "global:gid")

    async def test_mark_match_discovered_returns_false_for_existing_match(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_discovered(match_id=1001)

        self.assertFalse(result)

    async def test_claim_match_detail_allows_failed_retry(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        await repo.claim_match_detail(1001, lease_owner="owner", lease_seconds=60)

        filter_doc, update = db.jjc_sync_match_seen.find_one_and_update.call_args.kwargs["filter"], db.jjc_sync_match_seen.find_one_and_update.call_args.kwargs["update"]
        self.assertEqual(filter_doc["match_id"], 1001)
        self.assertEqual(filter_doc["status"], {"$in": ["discovered", "failed"]})
        self.assertEqual(update["$set"]["status"], "detail_syncing")


class TestJjcSyncRepoState(unittest.IsolatedAsyncioTestCase):
    async def test_get_paused_defaults_false_when_missing(self) -> None:
        db = FakeDb()
        db.jjc_sync_state.find_one.return_value = None
        repo = JjcSyncRepo(db=db)

        self.assertFalse(await repo.get_paused())

    async def test_set_paused_upserts_global_state(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.set_paused(True, "维护")

        self.assertTrue(result)
        call = db.jjc_sync_state.update_one.call_args
        self.assertEqual(call.args[0], {"key": "global"})
        self.assertTrue(call.kwargs["upsert"])
        self.assertTrue(call.args[1]["$set"]["paused"])
        self.assertEqual(call.args[1]["$set"]["reason"], "维护")


if __name__ == "__main__":
    unittest.main()
