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
        self.assertEqual(filter_doc, {"identity_key": "global:SK01-abc"})
        self.assertEqual(update["$set"]["identity_key"], "global_id:99999")
        self.assertEqual(update["$set"]["global_id"], "99999")
        self.assertNotIn("full_synced_until_time", update["$set"])
        self.assertIn("global:SK01-abc", update["$addToSet"]["aliases"]["$each"])

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
