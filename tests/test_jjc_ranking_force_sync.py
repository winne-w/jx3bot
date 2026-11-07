"""Behavior tests for ranking-triggered full-history sync requests."""
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from bson import ObjectId
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo
from tests.test_jjc_sync_worker_queue import MemoryDb, MemoryCollection


MEMBER = {"server": "fixture-server", "name": "fixture-role", "global_role_id": "SK01-fixture"}


class TestRankingForceSync(unittest.IsolatedAsyncioTestCase):
    def setup_queue(self, status="cooldown", priority=100, identity=False):
        self.identity_id = ObjectId()
        self.selector = {"identity_id": self.identity_id} if identity else {"identity_key": "global:SK01-fixture"}
        row = {"identity_key": "global:SK01-fixture", **self.selector, "status": status,
               "priority": priority, "fail_count": 3, "last_error": "previous failure",
               "next_sync_after": time.time()+3600, "queue_sync_until_time": 11,
               "queue_mode": "full", "queued_at": 1,
               "lease_owner": "worker", "lease_expires_at": time.time()+600}
        self.db = MemoryDb(roles=[row])
        if identity:
            self.db.jjc_sync_identity_queue = self.db.jjc_sync_role_queue
            self.db.role_identities = MemoryCollection([{"_id": self.identity_id}])
        self.repo = JjcSyncRepo(db=self.db)
        self.identity_patch = patch("src.storage.mongo_repos.role_identity_repo.RoleIdentityRepo.upsert_from_ranking_with_id",
                                    new=AsyncMock(return_value={"_id": self.identity_id, **row}))
        self.identity_patch.start()
        self.addCleanup(self.identity_patch.stop)
        return self.db.jjc_sync_role_queue.docs[0]

    async def request(self, order="0002:run", rank=5):
        return await self.repo.enqueue_ranking_member(MEMBER, request_order=order, rank=rank,
            batch_id=order, queue_sync_until_time=22, season_id="fixture-season", season_start_time=10)

    async def release(self, outcome="success"):
        if "identity_id" in self.selector:
            method = getattr(self.repo, "release_identity_"+outcome)
            key = self.identity_id
        else:
            method = getattr(self.repo, "release_role_"+outcome)
            key = self.selector["identity_key"]
        kwargs = {"reason": "cancelled"} if outcome == "interrupted" else {}
        return await method(key, lease_owner="worker", **kwargs)

    async def test_all_eligible_states_ignore_priority_and_due_time(self):
        for identity in (False, True):
            for status in ("pending", "cooldown", "exhausted", "failed", "queued"):
                for priority in (0, 1, 100):
                    with self.subTest(identity=identity,status=status,priority=priority):
                        row = self.setup_queue(status,priority,identity)
                        result = await self.request()
                        self.assertIsNotNone(result)
                        self.assertEqual(row["status"],"queued")
                        self.assertIsNone(row["next_sync_after"])
                        self.assertEqual(row["queue_front_order"],"0002:run")
                        self.assertEqual(row["queue_front_rank"],5)
                        self.assertEqual(row["priority"],max(1,priority))
                        self.assertEqual(row["fail_count"],3)
                        self.assertEqual(row["queue_sync_until_time"],22)

    async def test_disabled_is_untouched(self):
        for identity in (False,True):
            row=self.setup_queue("disabled",identity=identity)
            before=dict(row)
            await self.request()
            self.assertEqual(row["status"],"disabled")
            self.assertNotIn("ranking_request_order",row)
            self.assertEqual(row["queue_sync_until_time"],before["queue_sync_until_time"])

    async def test_same_or_older_request_does_not_requeue_after_success(self):
        row=self.setup_queue()
        await self.request()
        await self.repo.claim_queued_role("worker",600)
        self.assertTrue(await self.release())
        self.assertEqual(row["status"],"cooldown")
        await self.request()
        await self.request("0001:late")
        self.assertEqual(row["status"],"cooldown")
        await self.request("0003:next")
        self.assertEqual(row["status"],"queued")

    async def test_syncing_requests_coalesce_without_changing_current_execution(self):
        for identity in (False,True):
            for outcome in ("success","failure","interrupted"):
                with self.subTest(identity=identity,outcome=outcome):
                    row=self.setup_queue("syncing",identity=identity)
                    lease=row["lease_expires_at"]
                    await self.request("0002:first")
                    await self.request("0003:latest",rank=2)
                    await self.request("0001:late")
                    self.assertEqual(row["status"],"syncing")
                    self.assertEqual(row["lease_expires_at"],lease)
                    self.assertEqual(row["queue_sync_until_time"],11)
                    self.assertNotIn("season_id",row)
                    self.assertTrue(await self.release(outcome))
                    self.assertEqual(row["status"],"queued")
                    self.assertEqual(row["queue_front_order"],"0003:latest")
                    self.assertEqual(row["queue_sync_until_time"],22)
                    self.assertIsNone(row.get("ranking_pending"))
                    await self.repo.claim_queued_role("worker",600)
                    self.assertTrue(await self.release())
                    self.assertEqual(row["status"],"cooldown")
                    self.assertIsNone(row.get("queue_front_order"))

    async def test_failure_without_new_request_clears_front_and_keeps_backoff(self):
        row=self.setup_queue()
        await self.request()
        await self.repo.claim_queued_role("worker",600)
        self.assertTrue(await self.release("failure"))
        self.assertEqual(row["status"],"failed")
        self.assertGreater(row["next_sync_after"],time.time())
        self.assertIsNone(row.get("queue_front_order"))

    async def test_expired_lease_preserves_latest_request_and_rejects_old_owner(self):
        for identity in (False,True):
            row=self.setup_queue("syncing",identity=identity)
            await self.request()
            row["lease_expires_at"]=time.time()-1
            self.assertFalse(await self.release())
            recovered=await self.repo.recover_expired_leases()
            self.assertEqual(recovered,1)
            self.assertEqual(row["status"],"queued")
            self.assertEqual(row["queue_sync_until_time"],22)
            self.assertIsNone(row.get("ranking_pending"))

    async def test_release_retries_when_request_arrives_between_read_and_write(self):
        row=self.setup_queue("syncing")
        collection=self.db.jjc_sync_role_queue
        original=collection.update_one
        injected=False
        async def update(filter, update, **kwargs):
            nonlocal injected
            if not injected and update.get("$set",{}).get("status") in ("cooldown","queued"):
                injected=True
                await self.request("0004:racing")
            return await original(filter,update,**kwargs)
        collection.update_one=update
        self.assertTrue(await self.release())
        self.assertTrue(injected)
        self.assertEqual(row["status"],"queued")
        self.assertEqual(row["queue_front_order"],"0004:racing")

    async def test_request_retries_if_worker_claims_between_read_and_update(self):
        row=self.setup_queue("queued")
        collection=self.db.jjc_sync_role_queue
        original=collection.find_one_and_update
        injected=False
        async def update(filter, update, **kwargs):
            nonlocal injected
            if not injected and "ranking_request_order" in update.get("$set",{}):
                injected=True
                claimed=await self.repo.claim_queued_role("worker",600)
                self.assertEqual(claimed["queue_sync_until_time"],11)
            return await original(filter,update,**kwargs)
        collection.find_one_and_update=update
        await self.request()
        self.assertTrue(injected)
        self.assertEqual(row["status"],"syncing")
        self.assertEqual(row["queue_sync_until_time"],11)
        self.assertEqual(row["ranking_pending"]["queue_sync_until_time"],22)
        self.assertTrue(await self.release())
        self.assertEqual(row["status"],"queued")
        self.assertEqual(row["queue_sync_until_time"],22)

    async def test_priority_raised_during_request_is_not_downgraded(self):
        row=self.setup_queue(priority=0)
        collection=self.db.jjc_sync_role_queue
        original=collection.find_one_and_update
        async def update(filter, update, **kwargs):
            row["priority"]=1000
            return await original(filter,update,**kwargs)
        collection.find_one_and_update=update
        await self.request()
        self.assertEqual(row["priority"],1000)

    async def test_priority_raised_after_pending_request_is_kept_on_release(self):
        row=self.setup_queue("syncing")
        await self.request()
        row["priority"]=1000
        self.assertTrue(await self.release())
        self.assertEqual(row["priority"],1000)

    async def test_newest_batch_and_rank_order_match_list_and_positions(self):
        self.setup_queue()
        roles=self.db.jjc_sync_role_queue.docs
        roles[:]=[
            {"identity_key":"ordinary","status":"queued","priority":1000,"queued_at":0,"identity_id":ObjectId()},
            {"identity_key":"old","status":"queued","priority":100,"queued_at":1,"queue_front_order":"0001:a","queue_front_rank":1,"identity_id":ObjectId()},
            {"identity_key":"second","status":"queued","priority":1,"queued_at":2,"queue_front_order":"0002:b","queue_front_rank":2,"identity_id":ObjectId()},
            {"identity_key":"first","status":"queued","priority":1,"queued_at":3,"queue_front_order":"0002:b","queue_front_rank":1,"identity_id":ObjectId()},
        ]
        expected=["first","second","old","ordinary"]
        listing=await self.repo.list_queue(status="queued")
        self.assertEqual([x["identity_key"] for x in listing["items"]],expected)
        for i,key in enumerate(expected):
            doc=next(x for x in roles if x["identity_key"]==key)
            self.assertEqual(await self.repo.get_queue_position(doc),i+1)
        claimed=[(await self.repo.claim_queued_role("worker",600))["identity_key"] for _ in expected]
        self.assertEqual(claimed,expected)


class TestRankingRunContext(unittest.IsolatedAsyncioTestCase):
    def service(self):
        from src.services.jx3.jjc_ranking import JjcRankingService
        return JjcRankingService(token="",ticket="",jjc_query_url="",arena_time_tag_url="",
            arena_ranking_url="",match_detail_url="",jjc_ranking_cache_duration=0,kungfu_cache_duration=0,
            current_season="fixture",current_season_start="2026-11-05",kungfu_healer_list=[],
            kungfu_dps_list=["fixture-kungfu"],kungfu_pinyin_to_chinese={},
            tuilan_request=lambda *a: {},defget_get=AsyncMock())

    async def test_unknown_members_and_two_entries_share_one_run_but_next_run_is_new(self):
        from src.services.jx3.jjc_ranking import JjcRankingService
        service=self.service()
        board={"cache_time":12345,"data":[{"personInfo":{
            "server":MEMBER["server"],"roleName":MEMBER["name"],"globalRoleId":MEMBER["global_role_id"],
            "gameRoleId":"123","zone":"zone"},"score":2200}]}
        calls=[]
        class Sync:
            async def enqueue_ranking_member(self, member, **kwargs):
                calls.append((dict(member),kwargs))
                return {"status":"queued"}
        with patch.object(JjcRankingService,"get_user_kungfu",new=AsyncMock(return_value={"found":False})), \
             patch("src.services.jx3.jjc_ranking.JjcSyncRepo",Sync), \
             patch("src.services.jx3.jjc_ranking.JjcRankingStatsRepo") as stats, \
             patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED",0), \
             patch("src.services.jx3.jjc_ranking.cfg.JJC_KUNGFU_REFRESH_ENABLED",0), \
             patch("src.services.jx3.jjc_ranking.logger"):
            stats.return_value.save_snapshot=AsyncMock()
            first=await service.get_ranking_kungfu_data(board)
            self.assertEqual(len(calls),1,"unknown role must enter immediately")
            await service.save_ranking_stats(board,first["kungfu_statistics"],"week",payload=first)
            self.assertEqual(len(calls),2,"save must retry unknown members with same request")
            self.assertEqual(calls[0][1]["request_order"],calls[1][1]["request_order"])
            self.assertEqual(calls[0][1]["rank"],1)
            second=await service.get_ranking_kungfu_data(board)
            self.assertNotEqual(first["_sync_request"]["order"],second["_sync_request"]["order"])
            self.assertEqual(calls[-1][1]["request_order"],second["_sync_request"]["order"])
            self.assertNotIn("_sync_request",board)
            self.assertNotIn("_sync_request",stats.return_value.save_snapshot.call_args.kwargs["summary_payload"])

    async def test_unknown_member_outside_statistics_range_is_not_enqueued(self):
        service=self.service()
        self.assertTrue(service._should_enqueue_ranking_member_immediately(member=MEMBER,rank=1,total_players=201))
        self.assertFalse(service._should_enqueue_ranking_member_immediately(member=MEMBER,rank=201,total_players=201))


class TestRankingScheduledEntry(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_entry_forwards_sync_request_without_cache_flags(self):
        from tests.test_status_monitor_jobs_admin_notification import (
            _load_jobs, StatusMonitorJobsAdminNotificationTests,
        )
        module = _load_jobs()
        result={"kungfu_statistics":{"dps":{}},"_sync_request":{"order":"request","until":14}}
        StatusMonitorJobsAdminNotificationTests._prepare_ranking_job(
            module,
            ranking_result={"code": 0, "defaultWeek": 1, "cache_time": 1},
            ranking_data=result,
            payload={"image_bytes": b"image", "scope_desc": "fixture",
                     "total_valid_data": 1, "processed_label": "fixture"},
        )
        module.jjc_ranking_service.save_ranking_stats = Mock(return_value=None)
        await module.push_daily_jjc_ranking()
        self.assertEqual(module.jjc_ranking_service.save_ranking_stats.call_args.kwargs.get("payload"), result)
