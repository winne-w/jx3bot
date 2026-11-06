"""Isolated Mongo + actual services: cache cycle, frozen snapshots and recovery."""
import asyncio
from copy import deepcopy
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from src.infra.tuilan_kungfu_client import KungfuQueryError
from src.services.jx3.jjc_kungfu_policy import KungfuPolicy, make_scope
from src.services.jx3.jjc_kungfu_refresh import JjcKungfuRefreshService
from src.services.jx3.jjc_ranking import JjcRankingService
from src.storage.mongo_repos.jjc_kungfu_refresh_repo import JjcKungfuRefreshRepo
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo
from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo
from tests.test_jjc_kungfu_classifier import indicator, metric, wins
from tests.test_jjc_kungfu_refresh_mongo import checked_test_uri


@unittest.skipUnless(os.environ.get("JJC_TEST_MONGO_URI"), "explicit local Mongo URI required")
class RefreshIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncIOMotorClient(checked_test_uri(os.environ["JJC_TEST_MONGO_URI"]), serverSelectionTimeoutMS=3000)
        self.db_name = "jjc_kungfu_test_" + uuid4().hex
        self.db = self.client[self.db_name]
        await self.client.admin.command("ping")
        self.now = 2000000000.0
        self.policy = KungfuPolicy(make_scope("season-a", 1000), refresh_seconds=100,
                                   max_stale_seconds=300, track_seconds=1000)
        self.roles = RoleIdentityRepo(db=self.db)
        self.queue = JjcKungfuRefreshRepo(db=self.db)
        self.snapshots = JjcRankingStatsRepo(db=self.db, suppress_errors=False)
        self.identity = {"_id": ObjectId(), "identity_key": "game:zone-a:id-a",
            "server": "server-a", "normalized_server": "server-a", "name": "role-a",
            "normalized_name": "role-a", "zone": "zone-a", "game_role_id": "id-a",
            "role_id": "id-a", "updated_at": 123, "last_seen_at": 123}
        await self.db.role_identities.insert_one(deepcopy(self.identity))
        self.watermarks = {"full_synced_until_time": 123456, "oldest_synced_match_time": 111,
                           "latest_seen_match_time": 999, "history_exhausted": False, "last_cursor": 40}
        await self.db.jjc_sync_identity_queue.insert_one({"identity_id": self.identity["_id"],
            "identity_key": self.identity["identity_key"], "status": "pending", **self.watermarks})
        self.mode = "yunchang"
        self.upstream = SimpleNamespace(attempt_timeout=25, query=AsyncMock(side_effect=self.query))
        self.refresh = JjcKungfuRefreshService(self.roles, self.queue, self.upstream,
            self.policy, {"bingxin": "冰心诀", "yunchang": "云裳心经"}, clock=lambda: self.now)
        self.ranking = JjcRankingService(token="", ticket="", jjc_query_url="",
            arena_time_tag_url="", arena_ranking_url="", match_detail_url="",
            jjc_ranking_cache_duration=3600, kungfu_cache_duration=3600,
            current_season="season-a", current_season_start="1970-01-01",
            kungfu_healer_list=["云裳心经"], kungfu_dps_list=["冰心诀"],
            kungfu_pinyin_to_chinese={"bingxin": "冰心诀", "yunchang": "云裳心经"},
            tuilan_request=Mock(side_effect=AssertionError("foreground queried upstream")),
            defget_get=AsyncMock(side_effect=AssertionError("foreground used fallback")),
            identity_repo=self.roles, kungfu_refresh_repo=self.queue, kungfu_policy=self.policy)
        for patcher in [
            patch("src.services.jx3.jjc_ranking.time.time", side_effect=lambda: self.now),
            patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED", 1, create=True),
            patch("src.services.jx3.jjc_ranking.cfg.JJC_KUNGFU_REFRESH_ENABLED", 1, create=True),
            patch("src.services.jx3.jjc_ranking.JjcSyncRepo", return_value=JjcSyncRepo(db=self.db)),
            patch("src.storage.mongo_repos.role_identity_repo._get_db", return_value=self.db),
            patch("src.services.jx3.jjc_ranking.logger", Mock()),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)
        await self.refresh.initialize()

    async def asyncTearDown(self):
        self.assertTrue(self.db_name.startswith("jjc_kungfu_test_"))
        self.assertEqual(len(self.db_name), len("jjc_kungfu_test_") + 32)
        await self.client.drop_database(self.db_name)
        self.client.close()

    def ranking_input(self):
        return {"data": [{"personInfo": {"server": "server-a", "roleName": "role-a·server-a",
            "zone": "zone-a", "gameRoleId": "id-a"}, "score": 2200}], "cache_time": self.now}

    async def query(self, role, scope):
        self.assertEqual(role["_id"], self.identity["_id"])
        self.assertEqual(scope, self.policy.scope)
        # Old career main stays healer; ten new wins move classification to DPS.
        return {"indicator_data": indicator(metric("yunchang", 100)),
                "matches": wins(*([self.mode] * 10)), "requested_at": self.now,
                "verified_at": self.now}

    async def assert_watermarks_unchanged(self):
        row = await self.db.jjc_sync_identity_queue.find_one({"identity_id": self.identity["_id"]})
        self.assertEqual({key: row[key] for key in self.watermarks}, self.watermarks)

    async def refresh_once(self):
        before = await self.roles.get_by_id(self.identity["_id"])
        try:
            return await self.refresh.run_once()
        finally:
            after = await self.roles.get_by_id(self.identity["_id"])
            for field in ("updated_at", "last_seen_at", "profile_observed_at", "role_info_observed_match_time"):
                self.assertEqual((field in before, before.get(field)),
                                 (field in after, after.get(field)))

    async def test_cold_refresh_hot_switch_and_persisted_snapshot_are_independent(self):
        cold = await self.ranking.get_ranking_kungfu_data(self.ranking_input())
        self.assertNotIn("error", cold)
        self.assertEqual(cold["kungfu_statistics"]["top_50"]["kungfu_cache"]["unknown"], 1)
        self.assertIsNotNone(await self.queue.get_by_id(self.identity["_id"]))
        self.upstream.query.assert_not_awaited()
        self.assertTrue(await self.refresh_once())
        hot = await self.ranking.get_ranking_kungfu_data(self.ranking_input())
        healer = hot["kungfu_statistics"]["top_50"]["healer"]["members"]["云裳心经"][0]
        self.assertEqual(healer["kungfu_publish_version"], 1)
        self.assertEqual(hot["kungfu_statistics"]["top_50"]["kungfu_cache"]["coverage"], 1)
        frozen = deepcopy(hot)
        stamp = int(self.now)
        summary = self.ranking._build_summary_payload({"kungfu_statistics": hot["kungfu_statistics"],
            "kungfu_cache_scope": hot["kungfu_cache_scope"]})
        details = self.ranking._build_detail_payloads(hot["kungfu_statistics"])
        await self.snapshots.save_snapshot(stamp, summary, details)
        before = await self.db.jjc_ranking_stat_details.find({"timestamp": stamp}).to_list(None)
        summary_before = await self.db.jjc_ranking_stat_summaries.find_one({"timestamp": stamp})
        self.mode = "bingxin"
        self.now += 101
        stale = await self.ranking.resolve_ranking_kungfus(self.ranking_input())
        self.assertEqual(stale["members"][0]["kungfu"], "云裳心经")
        self.assertEqual(stale["members"][0]["kungfu_freshness"], "stale")
        self.assertTrue(await self.refresh_once())
        switched = await self.ranking.get_ranking_kungfu_data(self.ranking_input())
        dps = switched["kungfu_statistics"]["top_50"]["dps"]["members"]["冰心诀"][0]
        self.assertEqual(dps["kungfu_publish_version"], 2)
        self.assertEqual(dps["kungfu_source"], "match_history")
        self.assertEqual(hot, frozen)
        self.assertEqual(await self.db.jjc_ranking_stat_details.find({"timestamp": stamp}).to_list(None), before)
        self.assertEqual(next(d for d in before if d["kungfu"] == "云裳心经")["members"][0]["kungfu_publish_version"], 1)
        self.assertEqual(await self.db.jjc_ranking_stat_summaries.find_one({"timestamp": stamp}), summary_before)
        self.upstream.query.assert_awaited()
        self.assertEqual(self.upstream.query.await_count, 2)
        self.ranking.tuilan_request.assert_not_called()
        self.ranking.defget_get.assert_not_awaited()
        await self.assert_watermarks_unchanged()

    async def test_query_timeout_preserves_last_success_and_recovers_after_retry(self):
        await self.queue.register([self.identity], self.policy.scope, self.now)
        self.assertTrue(await self.refresh_once())
        original = (await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]
        self.now += 101
        self.upstream.query.side_effect = KungfuQueryError("request_timeout")
        self.assertTrue(await self.refresh_once())
        task = await self.queue.get_by_id(self.identity["_id"])
        self.assertEqual((task["status"], task["last_error_code"], task["consecutive_failures"]),
                         ("pending", "request_timeout", 1))
        self.assertEqual(task["next_run_at"], self.now + 60)
        self.assertEqual((await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"], original)
        self.assertFalse(await self.refresh_once())
        self.now += 60
        self.mode = "bingxin"
        self.upstream.query.side_effect = self.query
        self.assertTrue(await self.refresh_once())
        saved = (await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]
        self.assertEqual((saved["name"], saved["publish_version"]), ("冰心诀", 3))
        task = await self.queue.get_by_id(self.identity["_id"])
        self.assertEqual(task["consecutive_failures"], 0)
        self.assertIsNone(task["last_error_code"])
        await self.assert_watermarks_unchanged()

    async def test_publication_survives_crash_before_ack_and_is_readable_while_running(self):
        await self.queue.register([self.identity], self.policy.scope, self.now)
        with patch.object(JjcKungfuRefreshRepo, "complete", new_callable=AsyncMock,
                          side_effect=OSError("ack unavailable")):
            with self.assertRaises(OSError):
                await self.refresh_once()
        saved = (await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]
        self.assertEqual(saved["publish_version"], 1)
        self.assertEqual((await self.queue.get_by_id(self.identity["_id"]))["status"], "running")
        hot = await self.ranking.resolve_ranking_kungfus(self.ranking_input())
        self.assertTrue(hot["members"][0]["found"])
        self.assertEqual(hot["members"][0]["kungfu_publish_version"], 1)
        self.now += 90
        self.mode = "bingxin"
        self.assertTrue(await self.refresh_once())
        newer = (await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]
        self.assertEqual((newer["name"], newer["publish_version"]), ("冰心诀", 2))
        self.assertEqual((await self.queue.get_by_id(self.identity["_id"]))["status"], "pending")
        await self.assert_watermarks_unchanged()

    async def test_cancelled_attempt_is_reclaimed_at_lease_boundary_without_old_token_ack(self):
        await self.queue.register([self.identity], self.policy.scope, self.now)
        self.upstream.query.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.refresh_once()
        abandoned = await self.queue.get_by_id(self.identity["_id"])
        self.assertEqual(abandoned["status"], "running")
        self.assertNotIn("jjc_kungfu", await self.roles.get_by_id(self.identity["_id"]))
        self.now += 90
        self.upstream.query.side_effect = self.query
        self.assertTrue(await self.refresh_once())
        saved = (await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]
        self.assertEqual(saved["publish_version"], abandoned["generation"] + 1)
        current = await self.queue.get_by_id(self.identity["_id"])
        self.assertFalse(await self.queue.complete(abandoned, self.now, self.now, error_code="late_failure"))
        self.assertEqual(await self.queue.get_by_id(self.identity["_id"]), current)
        await self.assert_watermarks_unchanged()

    async def test_same_anchor_recompute_and_legacy_rollback_clear_unknown_rows(self):
        timestamp = int(self.now)
        unknown = {"rank": 1, "name": "role-a", "server": "server-a"}
        cold = {"top_50": {"unknown_members": [unknown], "healer": {"members": {}}, "dps": {"members": {}}}}
        hot = {"top_50": {"unknown_members": [], "healer": {"members": {}}, "dps": {"members": {"冰心诀": [unknown]}}}}
        legacy = {"top_50": {"healer": {"members": {}}, "dps": {"members": {"冰心诀": [unknown]}}}}
        for replacement in (hot, legacy):
            await self.snapshots.save_snapshot(timestamp, {}, self.ranking._build_detail_payloads(cold))
            await self.snapshots.save_snapshot(timestamp, {}, self.ranking._build_detail_payloads(replacement))
            flat = await self.snapshots.list_flat_members(timestamp, "top_50")
            self.assertEqual(flat["total"], 1)
            self.assertEqual(flat["items"][0]["lane"], "dps")

    async def test_real_bson_long_counter_remains_usable_after_refresh(self):
        from bson.int64 import Int64
        await self.queue.register([self.identity], self.policy.scope, self.now)
        await self.db.jjc_kungfu_refresh_queue.update_one({"_id": self.identity["_id"]}, {"$set": {"generation": Int64(7)}})
        self.assertTrue(await self.refresh_once())
        saved = (await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]
        self.assertIsInstance(saved["publish_version"], Int64)
        self.assertEqual(saved["publish_version"], 8)
        self.assertEqual(self.policy.evaluate(saved,self.now)["freshness"],"fresh")
        await self.assert_watermarks_unchanged()

    async def test_ten_role_full_refresh_rotation_ends_with_no_due_tasks(self):
        from time import perf_counter
        identities = [self.identity]
        for index in range(1,10):
            doc = dict(self.identity, _id=ObjectId(), identity_key="game:zone-a:id-%s" % index,
                       name="role-%s" % index, normalized_name="role-%s" % index,
                       game_role_id="id-%s" % index, role_id="id-%s" % index)
            await self.db.role_identities.insert_one(doc)
            identities.append(doc)
        await self.queue.register(identities,self.policy.scope,self.now)
        self.upstream.query.side_effect = None
        self.upstream.query.return_value = {
            "indicator_data": indicator(metric("yunchang", 100)), "matches": [],
            "requested_at": self.now, "verified_at": self.now}
        started=perf_counter()
        for _ in identities:
            self.assertTrue(await self.refresh_once())
        self.assertFalse(await self.refresh_once())
        self.assertEqual(await self.db.role_identities.count_documents({"jjc_kungfu.publish_version":1}),10)
        self.assertEqual(await self.db.jjc_kungfu_refresh_queue.count_documents({"status":"pending"}),10)
        self.assertEqual(await self.db.jjc_kungfu_refresh_queue.count_documents({"next_run_at":{"$lte":self.now}}),0)
        self.assertEqual(self.upstream.query.await_count,10)
        self.assertLess(perf_counter()-started,10)
        await self.assert_watermarks_unchanged()

    async def test_real_publication_response_lost_is_confirmed_by_readback(self):
        await self.queue.register([self.identity],self.policy.scope,self.now)
        publish = RoleIdentityRepo.publish_jjc_kungfu_if_newer
        async def save_then_lose_response(repo,*args,**kwargs):
            self.assertTrue(await publish(repo,*args,**kwargs))
            raise OSError("isolated publication response lost")
        with patch.object(RoleIdentityRepo,"publish_jjc_kungfu_if_newer",save_then_lose_response):
            self.assertTrue(await self.refresh_once())
        saved = (await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]
        task = await self.queue.get_by_id(self.identity["_id"])
        self.assertEqual(saved["publish_version"],1)
        self.assertEqual(task["status"],"pending")
        self.assertEqual(task["next_run_at"],saved["verified_at"]+self.policy.refresh_seconds)

    async def test_real_publication_response_and_readback_lost_wait_for_lease_recovery(self):
        await self.queue.register([self.identity],self.policy.scope,self.now)
        publish = RoleIdentityRepo.publish_jjc_kungfu_if_newer
        read = RoleIdentityRepo.get_by_id
        calls = 0
        async def save_then_lose_response(repo,*args,**kwargs):
            self.assertTrue(await publish(repo,*args,**kwargs))
            raise OSError("isolated publication response lost")
        async def unavailable_readback(repo,*args,**kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OSError("isolated readback lost")
            return await read(repo,*args,**kwargs)
        with patch.object(RoleIdentityRepo,"publish_jjc_kungfu_if_newer",save_then_lose_response), \
             patch.object(RoleIdentityRepo,"get_by_id",unavailable_readback):
            with self.assertRaises(OSError):
                await self.refresh.run_once()
        self.assertEqual((await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]["publish_version"],1)
        self.assertEqual((await self.queue.get_by_id(self.identity["_id"]))["status"],"running")
        self.now += 91
        self.assertTrue(await self.refresh_once())
        self.assertEqual((await self.roles.get_by_id(self.identity["_id"]))["jjc_kungfu"]["publish_version"],2)
        self.assertEqual((await self.queue.get_by_id(self.identity["_id"]))["status"],"pending")
        await self.assert_watermarks_unchanged()
