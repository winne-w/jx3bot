"""Run only against a disposable Mongo instance via JJC_TEST_MONGO_URI."""
import asyncio
import multiprocessing
import os
import time
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from motor.motor_asyncio import AsyncIOMotorClient

from src.services.jx3.jjc_live_refresh import JjcLiveRefreshService
from src.services.jx3.jjc_public_refresh import source_key, submit_refresh
from src.storage.mongo_repos.jjc_live_refresh_repo import JjcLiveRefreshRepo

URI = os.getenv("JJC_TEST_MONGO_URI", "")


def submit_in_process(args):
    uri, database, identity = args
    async def work():
        client = AsyncIOMotorClient(uri)
        try:
            repo = JjcLiveRefreshRepo(client[database], capacity=2)
            return await repo.submit(identity, "test")
        finally:
            client.close()
    return asyncio.run(work())


class IdentityRepo:
    async def find_best_by_name_with_id(self, server, name):
        if name == "known":
            return {"_id": "known", "global_role_id": "SK01-test", "server": server, "name": name}
        return None


@unittest.skipUnless(URI, "requires isolated JJC_TEST_MONGO_URI")
class TestLiveMongo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncIOMotorClient(URI)
        self.database = "jjc_refresh_test_" + uuid.uuid4().hex
        self.db = self.client[self.database]
        self.repo = JjcLiveRefreshRepo(self.db, capacity=2)
        await self.repo.initialize()

    async def asyncTearDown(self):
        await self.client.drop_database(self.database)
        self.client.close()

    async def test_cross_process_same_role_only_one_slot_then_capacity(self):
        with multiprocessing.get_context("spawn").Pool(4) as pool:
            await asyncio.to_thread(pool.map, submit_in_process,
                [(URI, self.database, {"_id": "same"})] * 12)
        self.assertEqual(await self.db.jjc_live_refresh_slots.count_documents({"state": "queued"}), 1)
        await asyncio.gather(*(self.repo.submit({"_id": str(i)}, "test") for i in range(8)))
        self.assertEqual(await self.db.jjc_live_refresh_slots.count_documents({"state": "queued"}), 2)

    async def test_expired_generation_cannot_publish_or_free_new_slot(self):
        await self.repo.submit({"_id": "known"}, "test")
        old = await self.repo.claim()
        future = time.time() + 200
        self.repo.clock = lambda: future
        await self.repo.submit({"_id": "known"}, "test")
        new = await self.repo.claim()
        self.assertNotEqual(old["generation"], new["generation"])
        self.assertFalse(await self.repo.publish(old, [{"match_id": 9, "match_time": 10}]))
        await self.repo.finish(old)
        self.assertEqual((await self.repo.state(new["task_key"]))["state"], "running")
        self.assertTrue(await self.repo.publish(new, [{"match_id": 10, "match_time": 20}]))
        self.assertEqual((await self.repo.read(new["task_key"]))["latest_matches"][0]["match_id"], 10)

    async def test_empty_success_is_cooled_down_and_counts_as_checked(self):
        await self.repo.submit({"_id": "known"}, "test")
        task = await self.repo.claim()
        self.assertTrue(await self.repo.publish(task, []))
        await self.repo.finish(task)
        state = await self.repo.submit({"_id": "known"}, "test")
        self.assertEqual(state["state"], "cooldown")
        self.assertIsNotNone(state["last_checked_at"])
        self.assertGreater(state["retry_after_seconds"], 0)

    async def test_read_uses_same_state_document_as_snapshot_pointer(self):
        await self.repo.submit({"_id": "known"}, "test")
        task = await self.repo.claim()
        await self.repo.publish(task, [{"match_id": 1, "match_time": 20}])
        with patch.object(self.repo, "state", AsyncMock(return_value={"state": "cooldown"})):
            data = await self.repo.read(task["task_key"])
        self.assertEqual("running", data["refresh"]["state"])
        self.assertEqual(1, data["latest_matches"][0]["match_id"])

    async def test_refresh_merges_old_summaries_and_preserves_them_on_second_page_failure(self):
        for second_fails in (False, True):
            with self.subTest(second_fails=second_fails):
                identity = {"_id": str(second_fails), "global_role_id": "SK01-test"}
                await self.repo.submit(identity, "test")
                old = await self.repo.claim()
                stamp = int(time.time()) - 100
                previous = [{"match_id": i, "match_time": stamp - i, "start_time": stamp - i} for i in range(1, 41)]
                await self.repo.publish(old, previous)
                await self.repo.finish(old)
                await self.db.jjc_live_refresh_state.update_one({"_id": old["task_key"]}, {"$set": {"next_allowed_at": 0}})
                await self.repo.submit(identity, "test")
                task = await self.repo.claim()
                class History:
                    def get_mine_match_history(self, **kwargs):
                        if kwargs["cursor"]:
                            return {"error": "request_failed"}
                        offset = 100 if second_fails else 0
                        return {"code": 0, "data": [
                            {"match_id": offset + i, "pvp_type": 3,
                             "start_time": stamp + offset - i} for i in range(1, 21)]}
                service = JjcLiveRefreshService(identity_repo=None, history_client=History(),
                    indicator_client=None, season="test", season_start=0, repo=self.repo)
                await service.execute(task)
                data = await self.repo.read(task["task_key"])
                self.assertEqual(40, len(data["latest_matches"]))
                self.assertEqual("refresh_failed" if second_fails else "cooldown", data["refresh"]["state"])
                ids = {row["match_id"] for row in data["latest_matches"]}
                self.assertIn(1, ids)
                self.assertIn(120 if second_fails else 40, ids)

    async def test_first_page_visible_before_second_and_no_detail_calls(self):
        first_saved = asyncio.Event()
        release_second = asyncio.Event()
        calls = []
        loop = asyncio.get_running_loop()
        class History:
            def get_mine_match_history(self, **kwargs):
                calls.append(kwargs["cursor"])
                if kwargs["cursor"] == 20:
                    loop.call_soon_threadsafe(first_saved.set)
                    asyncio.run_coroutine_threadsafe(release_second.wait(), loop).result(10)
                    return {"code": 0, "data": []}
                return {"code": 0, "data": [
                    {"match_id": i + 1, "pvp_type": 3, "start_time": int(time.time()) - i - 10,
                     "total_mmr": 2300, "mmr": 12} for i in range(20)]}
        service = JjcLiveRefreshService(identity_repo=IdentityRepo(), history_client=History(),
            indicator_client=None, season="test", season_start=0, repo=self.repo, enabled=lambda: True,
            readiness=lambda: {"state": "ready"})
        await self.repo.heartbeat("test-worker")
        self.assertEqual((await service.submit(server="server", name="known"))["state"], "queued")
        task = await self.repo.claim()
        running = asyncio.create_task(service.execute(task))
        try:
            await asyncio.wait_for(first_saved.wait(), 5)
            data = await service.read("known")
            self.assertEqual(len(data["latest_matches"]), 20)
            self.assertEqual(calls, [0, 20])
        finally:
            release_second.set()
            await running
        self.assertIsNotNone((await service.read("known"))["refresh"]["last_checked_at"])

    async def test_untrusted_forwarded_header_and_unknown_identity_never_call_upstream(self):
        self.assertEqual(source_key("10.0.0.2", "1.1.1.1", "", "test"),
                         source_key("10.0.0.2", "9.9.9.9", "", "test"))
        self.assertNotEqual(source_key("10.0.0.2", "1.1.1.1", "10.0.0.0/8", "test"),
                            source_key("10.0.0.2", "9.9.9.9", "10.0.0.0/8", "test"))
        service = JjcLiveRefreshService(identity_repo=IdentityRepo(), history_client=None,
            indicator_client=None, season="test", season_start=0, repo=self.repo, enabled=lambda: True,
            readiness=lambda: {"state": "ready"})
        await self.repo.heartbeat("test-worker")
        for _ in range(6):
            result, status = await submit_refresh(service, server="s", name="unknown", peer="10.0.0.2",
                forwarded="", trusted_proxies="", secret="test")
            self.assertEqual(result["state"], "identity_unavailable")
        result, status = await submit_refresh(service, server="s", name="unknown", peer="10.0.0.2",
            forwarded="9.9.9.9", trusted_proxies="", secret="test")
        self.assertEqual(status, 429)
