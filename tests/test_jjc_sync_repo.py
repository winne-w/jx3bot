import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

from bson import ObjectId
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


class FakeIdentityDb(FakeDb):
    def __init__(self) -> None:
        super().__init__()
        self.jjc_sync_identity_queue = FakeCollection()


class TestJjcSyncRepoIdentity(unittest.TestCase):
    def test_identity_key_priority(self) -> None:
        self.assertEqual(
            JjcSyncRepo._build_identity_key(
                global_id="99999",
                global_role_id="gid",
                zone="z",
                role_id="rid",
                normalized_server="s",
                normalized_name="n",
            ),
            "global_id:99999",
        )
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
        filter_doc, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "global:gid", "status": {"$ne": "syncing"}})
        self.assertNotIn("full_synced_until_time", update["$set"])
        self.assertNotIn("history_exhausted", update["$set"])
        self.assertNotIn("source", update["$set"])
        self.assertEqual(update["$max"], {"priority": -10})

    async def test_duplicate_insert_falls_back_to_update(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.side_effect = [None, {"identity_key": "global:gid"}]
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
        filter_doc, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "global:gid", "status": {"$ne": "syncing"}})
        self.assertEqual(update["$set"]["source"], "manual")

    async def test_upsert_existing_role_skips_syncing_without_update(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "global:gid",
            "status": "syncing",
            "lease_owner": "worker-1",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="gid",
            source="match_detail",
        )

        self.assertEqual(result, "global:gid")
        db.jjc_sync_role_queue.update_one.assert_not_called()

    async def test_upsert_existing_role_race_to_syncing_does_not_write(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {"identity_key": "global:gid", "status": "queued"}
        db.jjc_sync_role_queue.update_one.return_value = SimpleNamespace(
            matched_count=0,
            modified_count=0,
            upserted_id=None,
        )
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="gid",
            source="match_detail",
        )

        self.assertEqual(result, "global:gid")
        filter_doc, _ = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "global:gid", "status": {"$ne": "syncing"}})

    async def test_duplicate_insert_fallback_skips_syncing_role(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.side_effect = [
            None,
            {"identity_key": "global:gid", "status": "syncing", "lease_owner": "worker-1"},
        ]
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
        db.jjc_sync_role_queue.update_one.assert_not_called()

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
            global_id="99999",
            global_role_id="gid",
            role_id="rid",
            zone="zone-a",
            identity_source="role_identity_name_match",
        )

        self.assertTrue(result)
        filter_doc, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "name:梦江南:角色A"})
        self.assertEqual(update["$set"]["global_id"], "99999")
        self.assertEqual(update["$set"]["global_role_id"], "gid")
        self.assertEqual(update["$set"]["role_id"], "rid")
        self.assertEqual(update["$set"]["zone"], "zone-a")
        self.assertEqual(update["$set"]["identity_source"], "role_identity_name_match")
        self.assertNotIn("full_synced_until_time", update["$set"])

    async def test_update_role_identity_fields_with_lease_owner_uses_active_fence(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "name:梦江南:角色A",
            "status": "syncing",
            "lease_owner": "worker-1",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.update_role_identity_fields(
            identity_key="name:梦江南:角色A",
            global_role_id="gid",
            lease_owner="worker-1",
        )

        self.assertTrue(result)
        find_filter = db.jjc_sync_role_queue.find_one.call_args.args[0]
        self.assertEqual(find_filter["identity_key"], "name:梦江南:角色A")
        self.assertEqual(find_filter["status"], "syncing")
        self.assertEqual(find_filter["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", find_filter)
        self.assertGreater(find_filter["lease_expires_at"]["$gt"], 0)
        update_filter, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(update_filter["status"], "syncing")
        self.assertEqual(update_filter["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", update_filter)
        self.assertEqual(update["$set"]["global_role_id"], "gid")

    async def test_update_role_identity_fields_and_key_migrates_to_global_id_without_waterline_reset(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "name:梦江南:角色A",
            "normalized_server": "梦江南",
            "normalized_name": "角色A",
            "full_synced_until_time": 1000,
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.update_role_identity_fields_and_key(
            identity_key="name:梦江南:角色A",
            global_id="99999",
            global_role_id="SK01-abc",
            role_id="rid-a",
            zone="电信区",
            identity_source="role_identity_name_match",
        )

        self.assertEqual(result, "global_id:99999")
        filter_doc, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "name:梦江南:角色A"})
        self.assertEqual(update["$set"]["identity_key"], "global_id:99999")
        self.assertEqual(update["$set"]["global_id"], "99999")
        self.assertEqual(update["$set"]["global_role_id"], "SK01-abc")
        self.assertIn("name:梦江南:角色A", update["$addToSet"]["aliases"]["$each"])
        self.assertNotIn("full_synced_until_time", update["$set"])

    async def test_update_role_identity_fields_and_key_with_lease_owner_fences_current_worker(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "name:梦江南:角色A",
            "normalized_server": "梦江南",
            "normalized_name": "角色A",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.update_role_identity_fields_and_key(
            identity_key="name:梦江南:角色A",
            global_id="99999",
            global_role_id="SK01-abc",
            lease_owner="worker-1",
        )

        self.assertEqual(result, "global_id:99999")
        find_one_call = db.jjc_sync_role_queue.find_one.call_args
        self.assertEqual(find_one_call.args[0]["identity_key"], "name:梦江南:角色A")
        self.assertEqual(find_one_call.args[0]["status"], "syncing")
        self.assertEqual(find_one_call.args[0]["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", find_one_call.args[0])
        self.assertGreater(find_one_call.args[0]["lease_expires_at"]["$gt"], 0)
        filter_doc, _ = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc["status"], "syncing")
        self.assertEqual(filter_doc["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", filter_doc)
        self.assertGreater(filter_doc["lease_expires_at"]["$gt"], 0)

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
        self.assertEqual(role_update["$set"]["status"], "queued")
        self.assertEqual(role_update["$set"]["interrupted_reason"], "lease_expired")
        self.assertIn("queued_at", role_update["$set"])
        match_filter = db.jjc_sync_match_seen.update_many.call_args.kwargs["filter"]
        match_update = db.jjc_sync_match_seen.update_many.call_args.kwargs["update"]
        self.assertEqual(match_filter["status"], "detail_syncing")
        self.assertEqual(match_update["$set"]["status"], "discovered")

    async def test_claim_next_roles_prefers_queued_roles_for_compatibility(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one_and_update.return_value = {
            "identity_key": "global:gid",
            "status": "syncing",
        }
        repo = JjcSyncRepo(db=db)

        claimed = await repo.claim_next_roles(limit=1, lease_owner="owner", lease_seconds=60)

        self.assertEqual(len(claimed), 1)
        filter_doc = db.jjc_sync_role_queue.find_one_and_update.call_args.kwargs["filter"]
        self.assertEqual(filter_doc["status"], "queued")

    async def test_claim_next_roles_does_not_fallback_to_due_legacy_candidates(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one_and_update.return_value = None
        repo = JjcSyncRepo(db=db)

        claimed = await repo.claim_next_roles(limit=1, lease_owner="owner", lease_seconds=60)

        self.assertEqual(claimed, [])
        self.assertEqual(db.jjc_sync_role_queue.find_one_and_update.call_count, 1)
        filter_doc = db.jjc_sync_role_queue.find_one_and_update.call_args.kwargs["filter"]
        self.assertEqual(filter_doc["status"], "queued")

    async def test_get_queue_state_by_identity_id_reads_identity_queue_row(self) -> None:
        db = FakeDb()
        identity_id = ObjectId()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_id": identity_id,
            "status": "cooldown",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.get_queue_state_by_identity_id(str(identity_id))

        self.assertEqual(result["status"], "cooldown")
        self.assertEqual(db.jjc_sync_role_queue.find_one.call_args.args[0], {"identity_id": identity_id})

    async def test_enqueue_existing_identity_sets_fixed_priority_and_page_source(self) -> None:
        db = FakeDb()
        identity_id = ObjectId()
        queued_doc = {
            "identity_id": identity_id,
            "identity_key": "global_id:987",
            "status": "queued",
            "priority": 2,
            "queue_source": "synced_match_page",
        }
        db.jjc_sync_role_queue.find_one.return_value = None
        db.jjc_sync_role_queue.find_one_and_update.return_value = queued_doc
        repo = JjcSyncRepo(db=db)

        result = await repo.enqueue_existing_identity(
            {
                "_id": identity_id,
                "identity_key": "global_id:987",
                "server": "梦江南",
                "name": "角色A",
                "normalized_server": "梦江南",
                "normalized_name": "角色a",
            },
            priority=2,
            source="synced_match_page",
            mode="full",
            queue_sync_until_time=None,
        )

        self.assertIs(result, queued_doc)
        call = db.jjc_sync_role_queue.find_one_and_update.call_args
        self.assertEqual(call.kwargs["filter"]["identity_id"], identity_id)
        self.assertEqual(call.kwargs["filter"]["status"], {"$nin": ["disabled", "syncing"]})
        update = call.kwargs["update"]
        self.assertEqual(update["$set"]["priority"], 2)
        self.assertEqual(update["$set"]["status"], "queued")
        self.assertEqual(update["$set"]["identity_id"], identity_id)
        self.assertNotIn("identity_id", update["$setOnInsert"])
        self.assertEqual(update["$set"]["queue_source"], "synced_match_page")
        self.assertEqual(update["$set"]["queue_mode"], "full")
        self.assertIsNone(update["$set"]["queue_sync_until_time"])
        self.assertEqual(update["$setOnInsert"]["source"], "synced_match_page")

    async def test_enqueue_existing_identity_uses_identity_queue_when_available(self) -> None:
        db = FakeIdentityDb()
        identity_id = ObjectId()
        queued_doc = {
            "identity_id": identity_id,
            "identity_key": "global_id:987",
            "status": "queued",
            "priority": 2,
            "queue_source": "synced_match_page",
        }
        db.jjc_sync_identity_queue.find_one.return_value = {
            "identity_id": identity_id,
            "identity_key": "global_id:987",
            "status": "pending",
            "priority": 0,
        }
        db.jjc_sync_identity_queue.find_one_and_update.return_value = queued_doc
        repo = JjcSyncRepo(db=db)

        result = await repo.enqueue_existing_identity(
            {
                "_id": identity_id,
                "identity_key": "global_id:987",
                "server": "梦江南",
                "name": "角色A",
            },
            priority=2,
            source="synced_match_page",
            mode="incremental_or_full",
        )

        self.assertIs(result, queued_doc)
        db.jjc_sync_role_queue.find_one.assert_not_called()
        db.jjc_sync_role_queue.find_one_and_update.assert_not_called()
        state_filter = db.jjc_sync_identity_queue.find_one.call_args.args[0]
        self.assertEqual(state_filter, {"identity_id": identity_id})
        update_call = db.jjc_sync_identity_queue.find_one_and_update.call_args
        self.assertEqual(update_call.kwargs["filter"], {
            "identity_id": identity_id,
            "status": {"$nin": ["disabled", "syncing"]},
        })
        self.assertEqual(update_call.kwargs["update"]["$set"]["status"], "queued")
        self.assertEqual(update_call.kwargs["update"]["$set"]["priority"], 2)
        self.assertEqual(update_call.kwargs["update"]["$set"]["identity_id"], identity_id)
        self.assertNotIn("identity_id", update_call.kwargs["update"]["$setOnInsert"])

    async def test_enqueue_existing_identity_returns_syncing_state_without_lease_update(self) -> None:
        db = FakeDb()
        identity_id = ObjectId()
        syncing_doc = {
            "identity_id": identity_id,
            "status": "syncing",
            "lease_owner": "worker-1",
        }
        db.jjc_sync_role_queue.find_one.return_value = syncing_doc
        repo = JjcSyncRepo(db=db)

        result = await repo.enqueue_existing_identity(
            {"_id": identity_id, "identity_key": "global_id:987"},
            priority=2,
            source="synced_match_page",
            mode="incremental_or_full",
        )

        self.assertIs(result, syncing_doc)
        db.jjc_sync_role_queue.find_one_and_update.assert_not_called()

    async def test_upsert_role_prefers_global_id_and_writes_sk01_as_profile_field(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="SK01-abc",
            role_id="rid-a",
            zone="电信区",
            global_id="99999",
        )

        self.assertEqual(result, "global_id:99999")
        inserted = db.jjc_sync_role_queue.insert_one.call_args.args[0]
        self.assertEqual(inserted["identity_key"], "global_id:99999")
        self.assertEqual(inserted["global_id"], "99999")
        self.assertEqual(inserted["global_role_id"], "SK01-abc")

    async def test_upsert_role_migrates_legacy_global_role_queue_record(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.side_effect = [
            None,
            {
                "identity_key": "global:SK01-abc",
                "full_synced_until_time": 1000,
                "history_exhausted": True,
            },
        ]
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="SK01-abc",
            role_id="rid-a",
            zone="电信区",
            global_id="99999",
            priority=5,
        )

        self.assertEqual(result, "global_id:99999")
        db.jjc_sync_role_queue.insert_one.assert_not_called()
        filter_doc, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(filter_doc, {"identity_key": "global:SK01-abc", "status": {"$ne": "syncing"}})
        self.assertEqual(update["$set"]["identity_key"], "global_id:99999")
        self.assertEqual(update["$set"]["global_id"], "99999")
        self.assertNotIn("full_synced_until_time", update["$set"])
        self.assertIn("global:SK01-abc", update["$addToSet"]["aliases"]["$each"])

    async def test_upsert_role_migration_toctou_keeps_old_key_without_fallback_write(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.side_effect = [
            None,
            {
                "identity_key": "global:SK01-abc",
                "status": "pending",
                "full_synced_until_time": 1000,
            },
        ]
        db.jjc_sync_role_queue.update_one.side_effect = [
            SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None),
            SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None),
        ]
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="SK01-abc",
            role_id="rid-a",
            zone="电信区",
            global_id="99999",
            priority=5,
        )

        self.assertEqual(result, "global:SK01-abc")
        self.assertEqual(db.jjc_sync_role_queue.update_one.call_count, 1)
        first_filter, first_update = db.jjc_sync_role_queue.update_one.call_args_list[0].args
        self.assertEqual(first_filter, {"identity_key": "global:SK01-abc", "status": {"$ne": "syncing"}})
        self.assertEqual(first_update["$set"]["identity_key"], "global_id:99999")

    async def test_upsert_role_defers_legacy_key_migration_when_role_is_syncing(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.side_effect = [
            None,
            {
                "identity_key": "global:SK01-abc",
                "status": "syncing",
                "lease_owner": "worker-1",
                "full_synced_until_time": 1000,
            },
        ]
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="SK01-abc",
            role_id="rid-a",
            zone="电信区",
            global_id="99999",
            priority=5,
        )

        self.assertEqual(result, "global:SK01-abc")
        db.jjc_sync_role_queue.update_one.assert_not_called()

    async def test_upsert_role_skips_existing_syncing_role_profile_update(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "global_id:99999",
            "status": "syncing",
            "lease_owner": "worker-1",
            "global_id": "99999",
            "global_role_id": "SK01-abc",
            "full_synced_until_time": 1000,
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A-新名",
            normalized_server="梦江南",
            normalized_name="角色A-新名",
            global_role_id="SK01-abc",
            role_id="rid-a",
            zone="电信区",
            global_id="99999",
            priority=50,
        )

        self.assertEqual(result, "global_id:99999")
        db.jjc_sync_role_queue.update_one.assert_not_called()

    async def test_upsert_role_skips_legacy_migration_on_global_id_conflict(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.side_effect = [
            None,
            {
                "identity_key": "global:SK01-abc",
                "global_id": "88888",
                "full_synced_until_time": 1000,
            },
        ]
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="梦江南",
            name="角色A",
            normalized_server="梦江南",
            normalized_name="角色A",
            global_role_id="SK01-abc",
            role_id="rid-a",
            zone="电信区",
            global_id="99999",
            priority=5,
        )

        self.assertEqual(result, "global:SK01-abc")
        db.jjc_sync_role_queue.update_one.assert_not_called()

    async def test_upsert_role_old_match_does_not_overwrite_profile_fields(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "global_id:99999",
            "global_id": "99999",
            "server": "新服",
            "name": "新名",
            "normalized_server": "新服",
            "normalized_name": "新名",
            "role_id": "rid-new",
            "global_role_id": "SK01-new",
            "role_info_observed_match_time": 1810000100,
            "full_synced_until_time": 1000,
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="老服",
            name="旧名",
            normalized_server="老服",
            normalized_name="旧名",
            global_id="99999",
            global_role_id="SK01-old",
            role_id="rid-old",
            source="match_detail",
            observed_match_time=1810000000,
        )

        self.assertEqual(result, "global_id:99999")
        _, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertNotIn("server", update["$set"])
        self.assertNotIn("name", update["$set"])
        self.assertNotIn("role_id", update["$set"])
        self.assertNotIn("global_role_id", update["$set"])
        self.assertNotIn("role_info_observed_match_time", update["$set"])
        self.assertNotIn("full_synced_until_time", update["$set"])

    async def test_upsert_role_newer_match_overwrites_profile_fields(self) -> None:
        db = FakeDb()
        db.jjc_sync_role_queue.find_one.return_value = {
            "identity_key": "global_id:99999",
            "global_id": "99999",
            "server": "旧服",
            "name": "旧名",
            "normalized_server": "旧服",
            "normalized_name": "旧名",
            "role_id": "rid-old",
            "global_role_id": "SK01-old",
            "role_info_observed_match_time": 1810000000,
            "full_synced_until_time": 1000,
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.upsert_role(
            server="新服",
            name="新名",
            normalized_server="新服",
            normalized_name="新名",
            global_id="99999",
            global_role_id="SK01-new",
            role_id="rid-new",
            source="match_detail",
            observed_match_time=1810000100,
        )

        self.assertEqual(result, "global_id:99999")
        _, update = db.jjc_sync_role_queue.update_one.call_args.args
        self.assertEqual(update["$set"]["server"], "新服")
        self.assertEqual(update["$set"]["name"], "新名")
        self.assertEqual(update["$set"]["role_id"], "rid-new")
        self.assertEqual(update["$set"]["global_role_id"], "SK01-new")
        self.assertEqual(update["$set"]["role_info_observed_match_time"], 1810000100)
        self.assertNotIn("full_synced_until_time", update["$set"])


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

    async def test_claim_match_detail_filter_allows_discovered(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one_and_update.return_value = {
            "match_id": 1001,
            "status": "detail_syncing",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.claim_match_detail(1001, lease_owner="owner", lease_seconds=60)

        self.assertIsNotNone(result)
        kwargs = db.jjc_sync_match_seen.find_one_and_update.call_args.kwargs
        filter_doc = kwargs["filter"]
        self.assertEqual(filter_doc["match_id"], 1001)
        # filter must include discovered and failed-with-due-retry
        or_conditions = filter_doc["$or"]
        self.assertEqual(len(or_conditions), 2)
        self.assertEqual(or_conditions[0], {"status": "discovered"})
        self.assertEqual(or_conditions[1]["status"], "failed")
        self.assertEqual(kwargs["update"]["$set"]["status"], "detail_syncing")

    async def test_claim_match_detail_returns_none_when_no_match(self) -> None:
        db = FakeDb()
        # find_one_and_update default returns None → not claimable
        repo = JjcSyncRepo(db=db)

        result = await repo.claim_match_detail(1001)

        self.assertIsNone(result)

    async def test_claim_match_detail_returns_none_for_bad_id(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.claim_match_detail("not-a-number")

        self.assertIsNone(result)
        db.jjc_sync_match_seen.find_one_and_update.assert_not_called()

    async def test_get_match_detail_sync_state_terminal_returns_skip_action(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {
            "match_id": 1001,
            "status": "detail_saved",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.get_match_detail_sync_state(1001)

        self.assertEqual(result["action"], "skip")
        self.assertTrue(result["terminal"])
        self.assertFalse(result["claimable"])

    async def test_get_match_detail_sync_state_non_terminal_returns_interrupt_action(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {
            "match_id": 1001,
            "status": "detail_syncing",
            "lease_owner": "worker-1",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.get_match_detail_sync_state(1001)

        self.assertEqual(result["action"], "interrupt")
        self.assertFalse(result["terminal"])
        self.assertFalse(result["claimable"])

    async def test_get_match_detail_sync_state_due_failed_returns_claimable_action(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {
            "match_id": 1001,
            "status": "failed",
            "detail_retry_after": None,
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.get_match_detail_sync_state(1001)

        self.assertEqual(result["action"], "claimable")
        self.assertFalse(result["terminal"])
        self.assertTrue(result["claimable"])

    async def test_get_match_seen_doc_returns_full_document(self) -> None:
        db = FakeDb()
        source_identity_id = ObjectId()
        db.jjc_sync_match_seen.find_one.return_value = {
            "match_id": 1001,
            "status": "detail_saved",
            "detail_saved_at": 123.4,
            "source_identity_id": source_identity_id,
            "source_identity_key": "global_id:abc",
        }
        repo = JjcSyncRepo(db=db)

        result = await repo.get_match_seen_doc("1001")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["detail_saved_at"], 123.4)
        self.assertEqual(result["source_identity_id"], source_identity_id)
        db.jjc_sync_match_seen.find_one.assert_called_once_with({"match_id": 1001})

    async def test_mark_match_detail_unavailable_writes_fields_and_clears_lease(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_unavailable(
            match_id="2001",
            reason="不存在",
            code="1",
        )

        self.assertTrue(result)
        filter_doc, update = db.jjc_sync_match_seen.update_one.call_args.args
        self.assertEqual(filter_doc, {"match_id": 2001})
        set_fields = update["$set"]
        self.assertEqual(set_fields["status"], "detail_unavailable")
        self.assertEqual(set_fields["detail_unavailable_reason"], "不存在")
        self.assertEqual(set_fields["detail_unavailable_code"], 1)
        self.assertIsNotNone(set_fields["detail_unavailable_at"])
        self.assertIsNone(set_fields["lease_owner"])
        self.assertIsNone(set_fields["lease_expires_at"])
        self.assertIsNone(set_fields["detail_retry_after"])

    async def test_mark_match_detail_saved_with_lease_owner_uses_fenced_filter(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_saved(2002, lease_owner="worker-1")

        self.assertTrue(result)
        filter_doc, update = db.jjc_sync_match_seen.update_one.call_args.args
        self.assertEqual(filter_doc["match_id"], 2002)
        self.assertEqual(filter_doc["status"], "detail_syncing")
        self.assertEqual(filter_doc["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", filter_doc)
        self.assertGreater(filter_doc["lease_expires_at"]["$gt"], 0)
        self.assertEqual(update["$set"]["status"], "detail_saved")

    async def test_mark_match_detail_saved_returns_false_for_stale_lease(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.update_one.return_value = SimpleNamespace(
            matched_count=0,
            modified_count=0,
            upserted_id=None,
        )
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_saved(2003, lease_owner="worker-1")

        self.assertFalse(result)

    async def test_renew_match_detail_lease_requires_current_owner(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.renew_match_detail_lease(2004, lease_owner="worker-1", lease_seconds=60)

        self.assertTrue(result)
        filter_doc, update = db.jjc_sync_match_seen.update_one.call_args.args
        self.assertEqual(filter_doc["match_id"], 2004)
        self.assertEqual(filter_doc["status"], "detail_syncing")
        self.assertEqual(filter_doc["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", filter_doc)
        self.assertGreater(filter_doc["lease_expires_at"]["$gt"], 0)
        self.assertGreater(update["$set"]["lease_expires_at"], 0)

    async def test_renew_match_detail_lease_returns_false_for_stale_owner(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.update_one.return_value = SimpleNamespace(
            matched_count=0,
            modified_count=0,
            upserted_id=None,
        )
        repo = JjcSyncRepo(db=db)

        result = await repo.renew_match_detail_lease(2005, lease_owner="worker-old", lease_seconds=60)

        self.assertFalse(result)

    async def test_mark_match_detail_unavailable_returns_false_for_bad_id(self) -> None:
        db = FakeDb()
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_unavailable(match_id="bad")

        self.assertFalse(result)
        db.jjc_sync_match_seen.update_one.assert_not_called()

    async def test_mark_match_detail_failed_backoff_1st_failure(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {"fail_count": 0}
        repo = JjcSyncRepo(db=db)

        await repo.mark_match_detail_failed(3001, "err")

        _, update = db.jjc_sync_match_seen.update_one.call_args.args
        set_fields = update["$set"]
        self.assertEqual(set_fields["fail_count"], 1)
        self.assertAlmostEqual(set_fields["detail_retry_after"], set_fields["updated_at"] + 300, delta=2)

    async def test_mark_match_detail_failed_with_lease_owner_uses_fenced_filter(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {"fail_count": 0}
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_failed(3002, "err", lease_owner="worker-1")

        self.assertTrue(result)
        find_one_call = db.jjc_sync_match_seen.find_one.call_args
        self.assertEqual(find_one_call.args[0]["match_id"], 3002)
        self.assertEqual(find_one_call.args[0]["status"], "detail_syncing")
        self.assertEqual(find_one_call.args[0]["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", find_one_call.args[0])
        self.assertGreater(find_one_call.args[0]["lease_expires_at"]["$gt"], 0)
        self.assertEqual(find_one_call.args[1], {"fail_count": 1})
        filter_doc, update = db.jjc_sync_match_seen.update_one.call_args.args
        self.assertEqual(filter_doc["match_id"], 3002)
        self.assertEqual(filter_doc["status"], "detail_syncing")
        self.assertEqual(filter_doc["lease_owner"], "worker-1")
        self.assertIn("lease_expires_at", filter_doc)
        self.assertGreater(filter_doc["lease_expires_at"]["$gt"], 0)
        self.assertEqual(update["$set"]["fail_count"], 1)

    async def test_mark_match_detail_failed_returns_false_for_stale_lease(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = None
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_failed(3003, "err", lease_owner="worker-1")

        self.assertFalse(result)
        db.jjc_sync_match_seen.update_one.assert_not_called()

    async def test_mark_match_detail_failed_backoff_2nd_failure(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {"fail_count": 1}
        repo = JjcSyncRepo(db=db)

        await repo.mark_match_detail_failed(3001, "err")

        _, update = db.jjc_sync_match_seen.update_one.call_args.args
        set_fields = update["$set"]
        self.assertEqual(set_fields["fail_count"], 2)
        self.assertAlmostEqual(set_fields["detail_retry_after"], set_fields["updated_at"] + 1800, delta=2)

    async def test_mark_match_detail_failed_backoff_3rd_failure(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {"fail_count": 2}
        repo = JjcSyncRepo(db=db)

        await repo.mark_match_detail_failed(3001, "err")

        _, update = db.jjc_sync_match_seen.update_one.call_args.args
        set_fields = update["$set"]
        self.assertEqual(set_fields["fail_count"], 3)
        self.assertAlmostEqual(set_fields["detail_retry_after"], set_fields["updated_at"] + 7200, delta=2)

    async def test_mark_match_detail_failed_backoff_4th_failure_capped(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {"fail_count": 3}
        repo = JjcSyncRepo(db=db)

        await repo.mark_match_detail_failed(3001, "err")

        _, update = db.jjc_sync_match_seen.update_one.call_args.args
        set_fields = update["$set"]
        self.assertEqual(set_fields["fail_count"], 4)
        self.assertAlmostEqual(set_fields["detail_retry_after"], set_fields["updated_at"] + 21600, delta=2)

    async def test_mark_match_detail_failed_backoff_5th_failure_still_capped(self) -> None:
        db = FakeDb()
        db.jjc_sync_match_seen.find_one.return_value = {"fail_count": 4}
        repo = JjcSyncRepo(db=db)

        await repo.mark_match_detail_failed(3001, "err")

        _, update = db.jjc_sync_match_seen.update_one.call_args.args
        set_fields = update["$set"]
        self.assertEqual(set_fields["fail_count"], 5)
        self.assertAlmostEqual(set_fields["detail_retry_after"], set_fields["updated_at"] + 21600, delta=2)


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
