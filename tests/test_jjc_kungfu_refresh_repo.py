"""Queue contracts: no production Mongo connection is used by these unit tests."""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, MagicMock

from bson import ObjectId

from src.storage.mongo_repos.jjc_kungfu_refresh_repo import JjcKungfuRefreshRepo, QueueIntegrityError


SCOPE = {"season_id": "test-season", "season_start": 100, "pvp_type": 3, "algorithm_version": 1}


class TestRefreshQueueContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.col = MagicMock()
        self.col.find.return_value.to_list = AsyncMock(return_value=[])
        self.col.bulk_write = AsyncMock()
        self.col.find_one_and_update = AsyncMock(return_value=None)
        self.col.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        self.db = MagicMock()
        self.db.jjc_kungfu_refresh_queue = self.col
        self.repo = JjcKungfuRefreshRepo(db=self.db)
        self.identity = {"_id": ObjectId()}

    async def test_empty_batch_has_no_database_work(self):
        await self.repo.register([], SCOPE, 1000)
        self.col.find.assert_not_called()
        self.col.bulk_write.assert_not_awaited()

    async def test_task_missing_but_role_has_result_does_not_rebuild_online(self):
        self.identity["jjc_kungfu"] = {"publish_version": 9}
        with self.assertRaises(QueueIntegrityError):
            await self.repo.register([self.identity], SCOPE, 1000)
        self.col.bulk_write.assert_not_awaited()

    async def test_generation_behind_published_result_is_integrity_error(self):
        self.identity["jjc_kungfu"] = {"publish_version": 9}
        self.col.find.return_value.to_list.return_value = [{"_id": self.identity["_id"], "generation": 3, "scope": SCOPE}]
        with self.assertRaises(QueueIntegrityError):
            await self.repo.register([self.identity], SCOPE, 1000)

    async def test_complete_uses_all_execution_guards(self):
        task = {"_id": self.identity["_id"], "generation": 7, "lease_token": "fixture-lease", "scope": deepcopy(SCOPE)}
        self.assertTrue(await self.repo.complete(task, now=1000, next_run_at=2000))
        query, update = self.col.update_one.await_args.args
        self.assertEqual(query["_id"], task["_id"])
        self.assertEqual(query["generation"], 7)
        self.assertEqual(query["lease_token"], task["lease_token"])
        self.assertEqual(query["lease_expires_at"], {"$gt": 1000})
        self.assertEqual(query["status"], "running")
        for key, value in SCOPE.items():
            self.assertEqual(query["scope." + key], value)
        self.assertEqual(update["$set"]["status"], "pending")
        self.assertEqual(update["$set"]["next_run_at"], 2000)
        self.assertNotIn("jjc_kungfu", str(update))

    async def test_failure_increments_only_queue_failure_count(self):
        task = {"_id": self.identity["_id"], "generation": 1, "lease_token": "fixture-lease", "scope": SCOPE}
        await self.repo.complete(task, now=1000, next_run_at=1060, error_code="network_error")
        update = self.col.update_one.await_args.args[1]
        self.assertEqual(update["$inc"], {"consecutive_failures": 1})
        self.assertEqual(update["$set"]["last_error_code"], "network_error")
        self.assertNotIn("generation", update["$set"])

    async def test_claim_requires_scope_due_and_live_tracking(self):
        await self.repo.claim(SCOPE, now=1000, lease_seconds=90)
        query, update = self.col.find_one_and_update.await_args.args
        self.assertEqual(query["status"], "pending")
        self.assertEqual(query["next_run_at"], {"$lte": 1000})
        self.assertEqual(query["active_until"], {"$gt": 1000})
        self.assertEqual(update["$inc"], {"generation": 1})
        self.assertEqual(update["$set"]["lease_expires_at"], 1090)
        self.assertTrue(update["$set"]["lease_token"])

    async def test_completion_rejects_missing_lease_token_without_database_call(self):
        self.assertFalse(await self.repo.complete({"_id": self.identity["_id"], "generation": 1, "scope": SCOPE}, now=1000, next_run_at=2000))
        self.col.update_one.assert_not_awaited()
