"""Real Mongo verification, restricted to explicit disposable loopback databases."""
import asyncio
import os
import time
import unittest
from uuid import uuid4
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from tests.test_jjc_kungfu_refresh_mongo import checked_test_uri
from src.infra.mongo import _ensure_indexes
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo
from tests.test_jjc_ranking_force_sync import MEMBER


@unittest.skipUnless(os.environ.get("JJC_TEST_MONGO_URI"), "explicit isolated Mongo URI required")
class TestRankingForceSyncMongo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.uri=checked_test_uri(os.environ["JJC_TEST_MONGO_URI"])
        self.name="jjc_sync_front_test_"+uuid4().hex
        self.client=AsyncIOMotorClient(self.uri,serverSelectionTimeoutMS=3000)
        await self.client.admin.command("ping")
        self.db=self.client[self.name]
        await _ensure_indexes(self.db)
        self.repo=JjcSyncRepo(db=self.db)
        self.col=self.db.jjc_sync_identity_queue
        self.identity_id=ObjectId()
        self.selector={"identity_id":self.identity_id}

    async def asyncTearDown(self):
        checked_test_uri(self.uri)
        self.assertTrue(self.name.startswith("jjc_sync_front_test_"))
        self.assertEqual(len(self.name),len("jjc_sync_front_test_")+32)
        await self.client.drop_database(self.name)
        self.client.close()

    async def seed(self,status="syncing",**fields):
        await self.col.insert_one({**self.selector,"identity_key":"global:SK01-fixture",
            "status":status,"priority":100,"fail_count":3,"queue_sync_until_time":11,
            "next_sync_after":time.time()+3600,"lease_owner":"worker",
            "lease_expires_at":time.time()+600,**fields})

    async def request(self,order="0002:request",rank=1):
        return await self.repo._enqueue_ranking_request(self.selector,order,{
            "queue_batch_id":order,"queue_mode":"full","queue_source":"ranking_stats",
            "queue_sync_until_time":22,"queue_front_rank":rank,"priority":1,
            "season_id":"fixture","season_start_time":10})

    async def row(self):
        return await self.col.find_one(self.selector)

    async def test_public_identity_path_creates_one_queue_and_accepts_next_round(self):
        await self.repo.enqueue_ranking_member(MEMBER,request_order="0001:a",rank=1)
        row=await self.col.find_one({})
        self.assertIsNotNone(row["identity_id"])
        await self.repo.enqueue_ranking_member(MEMBER,request_order="0002:b",rank=1)
        self.assertEqual(await self.col.count_documents({}),1)
        self.assertEqual((await self.col.find_one({}))["queue_front_order"],"0002:b")

    async def test_public_identity_syncing_path_only_persists_pending_parameters(self):
        await self.repo.enqueue_ranking_member(MEMBER,request_order="0001:a",rank=1,
            season_id="old",queue_sync_until_time=11)
        claimed=await self.repo.claim_queued_role("worker",600)
        await self.repo.enqueue_ranking_member(MEMBER,request_order="0002:b",rank=1,
            season_id="new",queue_sync_until_time=22)
        row=await self.col.find_one({"identity_id":claimed["identity_id"]})
        self.assertEqual(row["season_id"],"old")
        self.assertEqual(row["queue_sync_until_time"],11)
        self.assertEqual(row["status"],"syncing")
        self.assertTrue(await self.repo.release_identity_success(claimed["identity_id"],lease_owner="worker"))
        row=await self.col.find_one({"identity_id":claimed["identity_id"]})
        self.assertEqual(row["season_id"],"new")
        self.assertEqual(row["queue_sync_until_time"],22)

    async def test_each_eligible_state_and_priority_are_forced_queued(self):
        for status in ("pending","cooldown","exhausted","failed","queued","disabled"):
            for priority in (0,1,100):
                await self.col.delete_many({})
                await self.seed(status,priority=priority)
                await self.request()
                row=await self.row()
                if status=="disabled":
                    self.assertEqual(row["status"],"disabled")
                else:
                    self.assertEqual(row["status"],"queued")
                    self.assertIsNone(row["next_sync_after"])
                    self.assertEqual(row["priority"],max(1,priority))

    async def test_concurrent_requests_and_single_claim(self):
        await self.seed("cooldown")
        await asyncio.gather(*(self.request("%04d:run"%i) for i in range(1,65)))
        self.assertEqual((await self.row())["ranking_request_order"],"0064:run")
        claims=await asyncio.gather(*(self.repo.claim_queued_role("worker-%s"%i,600) for i in range(20)))
        self.assertEqual(sum(row is not None for row in claims),1)
        self.assertIsNone((await self.row()).get("ranking_pending"))

    async def test_request_races_success_failure_and_interruption_release(self):
        for outcome in ("success","failure","interrupted"):
            for iteration in range(10):
                await self.col.delete_many({})
                await self.seed()
                release=getattr(self.repo,"release_identity_"+outcome)
                kwargs={"reason":"test"} if outcome=="interrupted" else {}
                results=await asyncio.gather(self.request("0002:a"),self.request("0003:b"),
                    release(self.identity_id,lease_owner="worker",**kwargs))
                self.assertTrue(results[-1])
                row=await self.row()
                self.assertEqual(row["ranking_request_order"],"0003:b")
                self.assertEqual(row["status"],"queued")
                self.assertEqual(row["queue_front_order"],"0003:b")
                self.assertEqual(row["queue_sync_until_time"],22)
                self.assertIsNone(row.get("ranking_pending"))
                await self.repo.claim_queued_role("worker",600)
                self.assertTrue(await self.repo.release_identity_success(self.identity_id,lease_owner="worker"))
                self.assertEqual((await self.row())["status"],"cooldown")
                await self.request("0003:b")
                self.assertEqual((await self.row())["status"],"cooldown")

    async def test_new_request_competes_with_worker_claim(self):
        for iteration in range(10):
            await self.col.delete_many({})
            await self.seed("queued",ranking_request_order="0001:old",queue_front_order="0001:old",queue_front_rank=1)
            claimed,_=await asyncio.gather(self.repo.claim_queued_role("worker",600),self.request())
            self.assertIsNotNone(claimed)
            current=await self.row()
            self.assertEqual(current["status"],"syncing")
            self.assertEqual(current["queue_sync_until_time"],claimed["queue_sync_until_time"])
            old_claim=claimed["ranking_request_order"]=="0001:old"
            self.assertEqual(bool(current.get("ranking_pending")),old_claim)
            self.assertTrue(await self.repo.release_identity_success(self.identity_id,lease_owner="worker"))
            current=await self.row()
            self.assertEqual(current["status"],"queued" if old_claim else "cooldown")
            self.assertEqual(current["ranking_request_order"],"0002:request")

    async def test_new_client_and_repo_restore_persisted_pending_after_consumer_restart(self):
        await self.seed()
        await self.request()
        self.client.close()
        self.client=AsyncIOMotorClient(self.uri,serverSelectionTimeoutMS=3000)
        self.db=self.client[self.name]
        self.col=self.db.jjc_sync_identity_queue
        self.repo=JjcSyncRepo(db=self.db)
        current=await self.row()
        self.assertEqual(current["status"],"syncing")
        self.assertEqual(current["ranking_pending"]["queue_sync_until_time"],22)
        await self.col.update_one(self.selector,{"$set":{"lease_expires_at":time.time()-1}})
        self.assertEqual(await self.repo.recover_expired_leases(),1)
        claimed=await self.repo.claim_queued_role("new-worker",600)
        self.assertEqual(claimed["queue_sync_until_time"],22)
        self.assertIsNone(claimed.get("ranking_pending"))
        self.assertTrue(await self.repo.release_identity_success(self.identity_id,lease_owner="new-worker"))
        self.assertEqual((await self.row())["status"],"cooldown")

    async def test_expiry_recovery_keeps_latest_request_and_fences_old_worker(self):
        await self.seed()
        await self.request()
        await self.col.update_one(self.selector,{"$set":{"lease_expires_at":time.time()-1}})
        self.assertFalse(await self.repo.release_identity_success(self.identity_id,lease_owner="worker"))
        self.assertEqual(await self.repo.recover_expired_leases(),1)
        row=await self.row()
        self.assertEqual(row["queue_sync_until_time"],22)
        self.assertEqual(row["queue_front_order"],"0002:request")
        await self.repo.claim_queued_role("new-worker",600)
        self.assertFalse(await self.repo.release_identity_failure(self.identity_id,lease_owner="worker"))
        self.assertEqual((await self.row())["lease_owner"],"new-worker")

    async def test_sort_positions_and_index_with_null_and_missing_metadata(self):
        docs=[
            {"identity_key":"missing","priority":1000,"queued_at":1},
            {"identity_key":"null","priority":1000,"queued_at":0,"queue_front_order":None,"queue_front_rank":None},
            {"identity_key":"old","priority":1,"queued_at":1,"queue_front_order":"0001:a","queue_front_rank":1},
            {"identity_key":"second","priority":1,"queued_at":1,"queue_front_order":"0002:b","queue_front_rank":2},
            {"identity_key":"first","priority":1,"queued_at":1,"queue_front_order":"0002:b","queue_front_rank":1},
        ]
        for doc in docs:
            await self.col.insert_one(dict(doc,status="queued",identity_id=ObjectId()))
        expected=["first","second","old","null","missing"]
        listing=await self.repo.list_queue(status="queued")
        self.assertEqual([row["identity_key"] for row in listing["items"]],expected)
        for i,row in enumerate(listing["items"]):
            self.assertEqual(await self.repo.get_queue_position(row),i+1)
        explain=await self.col.find({"status":"queued"}).sort(self.repo.QUEUE_SORT).hint("idx_status_ranking_front").explain()
        self.assertIn("idx_status_ranking_front",repr(explain))
        self.assertNotIn("'stage': 'SORT'",repr(explain["queryPlanner"]["winningPlan"]))
        for key in expected:
            self.assertEqual((await self.repo.claim_queued_role("worker",600))["identity_key"],key)
