"""Real Mongo CAS tests; only an explicit isolated local instance is allowed."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import multiprocessing
import os
import unittest
from urllib.parse import urlsplit
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from motor.motor_asyncio import AsyncIOMotorClient

from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo
from tests.test_role_identity_repo import recovery_snapshot


def checked_test_uri(uri):
    parsed = urlsplit(uri)
    if (parsed.scheme != "mongodb" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.port != 27029 or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or parsed.path not in {"", "/", "/jjc_test_role_identity"}):
        raise ValueError("Mongo tests require the isolated loopback instance on port 27029")
    return uri


def concurrent_cas_worker(uri, db_name, expected, observed_at, barrier, outcomes):
    async def run():
        client = AsyncIOMotorClient(checked_test_uri(uri), serverSelectionTimeoutMS=3000,
                                   tz_aware=True)
        try:
            repo = RoleIdentityRepo(db=client[db_name])
            await asyncio.to_thread(barrier.wait, 10)
            result = await repo.replace_query_ids_if_unchanged(
                expected, game_role_id="34945120", role_id="34945120", observed_at=observed_at)
            outcomes.put(("ok", result))
        except Exception as exc:
            outcomes.put(("error", repr(exc)))
        finally:
            client.close()
    asyncio.run(run())


class TestMongoUriSafety(unittest.TestCase):
    def test_rejects_remote_default_port_credentials_and_non_test_database(self):
        for uri in ["mongodb://production.invalid:27029/jjc_test_role_identity",
                    "mongodb://127.0.0.1:27017/", "mongodb://localhost:27029/production",
                    "mongodb://%s:%s@localhost:27029/" % (uuid4().hex, uuid4().hex),
                    "mongodb+srv://localhost/",
                    "mongodb://localhost:27029/?replicaSet=prod"]:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                checked_test_uri(uri)


@unittest.skipUnless(os.environ.get("JJC_TEST_MONGO_URI"), "explicit local Mongo URI required")
class TestQueryIdRecoveryMongo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.uri = checked_test_uri(os.environ["JJC_TEST_MONGO_URI"])
        self.db_name = "jjc_test_role_identity_" + uuid4().hex
        self.client = AsyncIOMotorClient(self.uri, serverSelectionTimeoutMS=3000, tz_aware=True)
        await self.client.admin.command("ping")
        self.db = self.client[self.db_name]
        self.repo = RoleIdentityRepo(db=self.db)
        self.before = recovery_snapshot()
        self.before.update(role_info_source="match_detail", role_info_updated_at=100.0,
                           last_seen_at=datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.observed_at = datetime(2026, 10, 20, tzinfo=timezone.utc)
        await self.db.role_identities.insert_one(deepcopy(self.before))

    async def asyncTearDown(self):
        checked_test_uri(self.uri)
        self.assertTrue(self.db_name.startswith("jjc_test_role_identity_"))
        self.assertEqual(len(self.db_name), len("jjc_test_role_identity_") + 32)
        await self.client.drop_database(self.db_name)
        self.client.close()

    async def replace(self, expected=None):
        method = getattr(self.repo, "replace_query_ids_if_unchanged", None)
        self.assertTrue(callable(method), "real Mongo CAS entry must exist")
        return await method(self.before if expected is None else expected,
                            game_role_id="34945120", role_id="34945120",
                            observed_at=self.observed_at)

    async def row(self):
        return await self.db.role_identities.find_one({"_id": self.before["_id"]})

    async def test_success_updates_only_ids_and_existing_observation_metadata(self):
        self.assertTrue(await self.replace())
        actual = await self.row()
        allowed = {"role_id", "game_role_id", "global_role_id_refreshed_at",
                   "global_role_id_refresh_source", "updated_at"}
        for key, value in self.before.items():
            if key not in allowed:
                self.assertEqual(actual[key], value, key)
        self.assertEqual(actual["role_id"], "34945120")
        self.assertEqual(actual["game_role_id"], "34945120")
        self.assertEqual(actual["global_role_id_refreshed_at"], self.observed_at)
        self.assertEqual(actual["updated_at"], self.observed_at)
        self.assertEqual(actual["global_role_id_refresh_source"], "indicator_replay_verified")
        self.assertEqual(set(actual) - set(self.before), {
            "global_role_id_refreshed_at", "global_role_id_refresh_source"})
        archived = await self.db.role_identities_history.find_one({})
        self.assertEqual(archived["role_id"], "31300496")

    async def test_each_combination_or_watermark_change_invalidates_prevalidated_snapshot(self):
        guarded = ["identity_key", "global_id", "global_role_id", "server", "normalized_server",
                   "name", "normalized_name", "zone", "role_id", "game_role_id", "person_id",
                   "profile_observed_at", "role_info_observed_match_time", "role_info_source",
                   "role_info_updated_at", "updated_at", "global_role_id_refreshed_at",
                   "global_role_id_refresh_source"]
        for field in guarded:
            with self.subTest(field=field):
                await self.db.role_identities.replace_one({"_id": self.before["_id"]},
                                                         deepcopy(self.before))
                await self.db.role_identities.update_one({"_id": self.before["_id"]},
                                                         {"$set": {field: "racing-writer"}})
                self.assertFalse(await self.replace(), field)
                self.assertEqual((await self.row())["role_id"],
                                 "racing-writer" if field == "role_id" else "31300496")

    async def test_missing_and_null_are_distinct_in_both_directions(self):
        for expected_null in (False, True):
            with self.subTest(expected_null=expected_null):
                before = deepcopy(self.before)
                before.pop("person_id")
                if expected_null:
                    before["person_id"] = None
                await self.db.role_identities.replace_one({"_id": before["_id"]}, before)
                mutation = {"$unset": {"person_id": ""}} if expected_null else {"$set": {"person_id": None}}
                await self.db.role_identities.update_one({"_id": before["_id"]}, mutation)
                self.assertFalse(await self.replace(before))
                self.assertEqual((await self.row())["role_id"], "31300496")

    async def test_real_archive_rejection_leaves_identity_unchanged(self):
        await self.db.create_collection("role_identities_history", validator={
            "$jsonSchema": {"bsonType": "object", "required": ["deliberately_absent"]}
        })
        self.assertFalse(await self.replace())
        self.assertEqual(await self.row(), self.before)

    async def test_retry_after_crash_at_successful_cas_does_not_reapply_stale_before_image(self):
        self.assertTrue(await self.replace())
        after = await self.row()
        self.assertFalse(await self.replace())
        self.assertEqual(await self.row(), after)

    async def test_historical_writer_that_read_before_repair_loses_its_profile_cas(self):
        stale = deepcopy(self.before)
        self.assertTrue(await self.replace())
        with patch.object(RoleIdentityRepo, "resolve_best_identity_with_id",
                          AsyncMock(return_value=stale)):
            returned = await self.repo.upsert_from_match_detail_with_id(
                server="old-server", name="old-name", zone="old-zone", global_id="10001",
                role_id="31300496", game_role_id="31300496", observed_match_time=9999999999)
        row = await self.row()
        self.assertEqual(row["server"], "new-server")
        self.assertEqual(row["role_id"], "34945120")
        self.assertEqual(returned["role_id"], "34945120")

    async def test_two_processes_can_only_publish_one_cas(self):
        self.assertTrue(callable(getattr(self.repo, "replace_query_ids_if_unchanged", None)))
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        outcomes = context.Queue()
        processes = [context.Process(target=concurrent_cas_worker, args=(
            self.uri, self.db_name, self.before, self.observed_at, barrier, outcomes)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                await asyncio.to_thread(process.join, 15)
                self.assertFalse(process.is_alive(), "worker exceeded bounded CAS test deadline")
                self.assertEqual(process.exitcode, 0)
            results = [outcomes.get(timeout=3) for _ in range(2)]
            self.assertTrue(all(status == "ok" for status, value in results), results)
            self.assertEqual(sorted(value for status, value in results), [False, True])
            self.assertEqual((await self.row())["role_id"], "34945120")
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    await asyncio.to_thread(process.join, 3)
            outcomes.close()

    async def test_repair_survives_old_same_and_future_historical_writers(self):
        self.assertTrue(await self.replace())
        for observed in (199, 200, 9999999999):
            await self.repo.upsert_from_match_detail_with_id(
                server="old-server", name="old-name", zone="old-zone", global_id="10001",
                role_id="31300496", game_role_id="31300496", observed_match_time=observed)
            row = await self.row()
            self.assertEqual(row["server"], "new-server")
            self.assertEqual(row["name"], "test-role")
            self.assertEqual(row["zone"], "zone-a")
            self.assertEqual(row["role_id"], "34945120")

    async def test_existing_strict_marker_alone_blocks_late_writer_without_new_api(self):
        await self.db.role_identities.update_one({"_id": self.before["_id"]}, {"$set": {
            "role_id": "34945120", "game_role_id": "34945120",
            "global_role_id_refreshed_at": self.observed_at,
            "global_role_id_refresh_source": "indicator_replay_verified",
        }})
        await self.repo.upsert_from_match_detail_with_id(
            server="old-server", name="old-name", zone="old-zone", global_id="10001",
            role_id="31300496", game_role_id="31300496", observed_match_time=9999999999)
        row = await self.row()
        self.assertEqual(row["server"], "new-server", "verified combination must not partially roll back")
        self.assertEqual(row["role_id"], "34945120")

    async def test_rollback_restores_original_missing_fields_without_reverting_sync_data(self):
        self.assertTrue(await self.replace())
        after = await self.row()
        await self.db.role_identities.update_one({"_id": self.before["_id"]},
                                                 {"$set": {"unrelated_sync_progress": 500}})
        rollback = getattr(self.repo, "rollback_query_ids_if_unchanged", None)
        self.assertTrue(callable(rollback))
        self.assertTrue(await rollback(after, self.before))
        row = await self.row()
        self.assertEqual(row["role_id"], "31300496")
        self.assertEqual(row["unrelated_sync_progress"], 500)
        self.assertNotIn("global_role_id_refreshed_at", row)
        self.assertNotIn("global_role_id_refresh_source", row)
        for field in ("identity_key", "global_id", "global_role_id", "role_info_observed_match_time"):
            self.assertEqual(row[field], self.before[field])

    async def test_rollback_skips_later_legal_identity_update(self):
        self.assertTrue(await self.replace())
        after = await self.row()
        await self.db.role_identities.update_one({"_id": self.before["_id"]},
                                                 {"$set": {"role_id": "later-id", "game_role_id": "later-id"}})
        rollback = getattr(self.repo, "rollback_query_ids_if_unchanged", None)
        self.assertTrue(callable(rollback))
        self.assertFalse(await rollback(after, self.before))
        self.assertEqual((await self.row())["role_id"], "later-id")

    async def test_rollback_restores_missing_id_and_null_id_exactly(self):
        before = deepcopy(self.before)
        before.pop("role_id")
        before["game_role_id"] = None
        await self.db.role_identities.replace_one({"_id": before["_id"]}, before)
        self.assertTrue(await self.replace(before))
        after = await self.row()
        self.assertTrue(await self.repo.rollback_query_ids_if_unchanged(after, before))
        self.assertEqual(await self.row(), before)
