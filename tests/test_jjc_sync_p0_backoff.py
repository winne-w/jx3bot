import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from bson import ObjectId

from src.services.jx3.jjc_match_data_sync import (
    JjcMatchDataSyncService,
    JjcSyncMatchDetailClaimError,
)
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo
from tests.test_jjc_match_data_sync import FakeHistoryClient, FakeInspectService, FakeRepo, _noop_sleep
from tests.test_jjc_sync_worker_queue import MemoryCollection, MemoryDb


class IdentityMemoryDb(MemoryDb):
    def __init__(
        self,
        identities_queue: Optional[List[Dict[str, Any]]] = None,
        matches: Optional[List[Dict[str, Any]]] = None,
        workers: Optional[List[Dict[str, Any]]] = None,
        states: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(roles=[], matches=matches, workers=workers, states=states)
        self.jjc_sync_identity_queue = MemoryCollection(identities_queue)


class TestJjcSyncP0Backoff(unittest.IsolatedAsyncioTestCase):
    async def test_failed_match_backoff_moves_role_to_cooldown_without_advancing_waterline(self) -> None:
        base_now = 1800000000.0
        retry_after = base_now + 3600.0
        identity_id = ObjectId()
        db = IdentityMemoryDb(
            identities_queue=[
                {
                    "identity_id": identity_id,
                    "identity_key": "global_id:10001",
                    "server": "梦江南",
                    "name": "测试角色",
                    "normalized_server": "梦江南",
                    "normalized_name": "测试角色",
                    "global_role_id": "SK01-10001",
                    "status": "queued",
                    "priority": 5,
                    "queued_at": base_now - 10.0,
                    "queue_mode": "full",
                    "queue_source": "ranking_stats",
                    "queue_batch_id": "batch-1",
                    "queue_front_order": "front-1",
                    "queue_front_rank": 1,
                    "full_synced_until_time": 1790000000,
                    "oldest_synced_match_time": 1789000000,
                    "latest_seen_match_time": 1790000000,
                    "history_exhausted": False,
                    "fail_count": 2,
                    "last_cursor": 0,
                }
            ],
            matches=[
                {
                    "match_id": 9001,
                    "status": "failed",
                    "detail_retry_after": retry_after,
                    "fail_count": 3,
                }
            ],
        )
        repo = JjcSyncRepo(db=db)
        history = FakeHistoryClient(
            [
                {
                    "data": [
                        {"match_id": 9001, "match_time": 1810000200, "pvpType": 3},
                        {"match_id": 9000, "match_time": 1810000100, "pvpType": 3},
                    ]
                }
            ]
        )
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        with patch("src.storage.mongo_repos.jjc_sync_repo.time.time", return_value=base_now), patch(
            "src.services.jx3.jjc_match_data_sync.time.time", return_value=base_now
        ):
            tick = await service.worker_tick(mode="full", worker_id="worker-1")
            reclaimed_early = await repo.claim_queued_role(lease_owner="worker-1", lease_seconds=600)
            enqueued_early = await repo.enqueue_next_roles(
                limit=5,
                mode="full",
                source="auto_dispatcher",
                batch_id="b-early",
            )

        self.assertFalse(tick["processed"])
        self.assertTrue(tick["result"]["interrupted"])
        self.assertEqual(tick["result"]["retry_after"], retry_after)
        self.assertIsNone(reclaimed_early)
        self.assertEqual(enqueued_early, [])

        row = db.jjc_sync_identity_queue.docs[0]
        self.assertEqual(row["status"], "cooldown")
        self.assertEqual(row["next_sync_after"], retry_after)
        self.assertIsNone(row["queued_at"])
        self.assertIsNone(row["queue_batch_id"])
        self.assertEqual(row["queue_source"], "interrupted")
        self.assertIsNone(row["queue_front_order"])
        self.assertIsNone(row["queue_front_rank"])
        self.assertIsNone(row["lease_owner"])
        self.assertIsNone(row["lease_expires_at"])
        # 同步水位与失败计数均不得被错误推进或修改
        self.assertEqual(row["full_synced_until_time"], 1790000000)
        self.assertEqual(row["oldest_synced_match_time"], 1789000000)
        self.assertEqual(row["latest_seen_match_time"], 1790000000)
        self.assertFalse(row["history_exhausted"])
        self.assertEqual(row["fail_count"], 2)

        with patch("src.storage.mongo_repos.jjc_sync_repo.time.time", return_value=retry_after + 1.0):
            enqueued_due = await repo.enqueue_next_roles(
                limit=5,
                mode="full",
                source="auto_dispatcher",
                batch_id="b-due",
            )
        self.assertEqual(len(enqueued_due), 1)
        self.assertEqual(enqueued_due[0]["status"], "queued")

    async def test_syncing_match_lease_moves_role_to_short_capped_cooldown(self) -> None:
        base_now = 1800000000.0
        lease_expires_at = base_now + 600.0
        db = MemoryDb(
            roles=[
                {
                    "identity_key": "global:role-syncing-wait",
                    "server": "梦江南",
                    "name": "等待者",
                    "normalized_server": "梦江南",
                    "normalized_name": "等待者",
                    "global_role_id": "SK01-WAIT",
                    "status": "queued",
                    "priority": 1,
                    "queued_at": base_now - 5.0,
                    "full_synced_until_time": 1795000000,
                    "fail_count": 0,
                }
            ],
            matches=[
                {
                    "match_id": 9002,
                    "status": "detail_syncing",
                    "lease_owner": "worker-other",
                    "lease_expires_at": lease_expires_at,
                }
            ],
        )
        repo = JjcSyncRepo(db=db)
        history = FakeHistoryClient(
            [{"data": [{"match_id": 9002, "match_time": 1810000300, "pvpType": 3}]}]
        )
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        with patch("src.storage.mongo_repos.jjc_sync_repo.time.time", return_value=base_now), patch(
            "src.services.jx3.jjc_match_data_sync.time.time", return_value=base_now
        ):
            tick = await service.worker_tick(mode="full", worker_id="worker-1")

        expected_retry_after = base_now + 30.0
        self.assertFalse(tick["processed"])
        self.assertTrue(tick["result"]["interrupted"])
        self.assertEqual(tick["result"]["retry_after"], expected_retry_after)

        row = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(row["status"], "cooldown")
        self.assertEqual(row["next_sync_after"], expected_retry_after)
        self.assertIsNone(row["queued_at"])
        self.assertEqual(row["queue_source"], "interrupted")
        self.assertEqual(row["full_synced_until_time"], 1795000000)

    async def test_syncing_status_alias_and_shorter_lease_uses_lease_expiry(self) -> None:
        base_now = 1800000000.0
        short_expiry = base_now + 12.5
        repo = FakeRepo()
        repo.detail_states[9003] = {
            "exists": True,
            "match_id": 9003,
            "status": "syncing",
            "action": "interrupt",
            "lease_expires_at": short_expiry,
        }
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        with patch("src.services.jx3.jjc_match_data_sync.time.time", return_value=base_now):
            with self.assertRaises(JjcSyncMatchDetailClaimError) as ctx:
                await service._sync_match_detail(
                    match_id=9003,
                    match_time=1810000000,
                    lease_owner="worker-1",
                )

        self.assertEqual(ctx.exception.retry_after, short_expiry)

    async def test_transient_claim_failure_and_claimable_race_requeue_immediately(self) -> None:
        base_now = 1800000000.0
        db = MemoryDb(
            roles=[
                {
                    "identity_key": "global:transient",
                    "server": "梦江南",
                    "name": "瞬时竞争",
                    "normalized_server": "梦江南",
                    "normalized_name": "瞬时竞争",
                    "global_role_id": "SK01-RACE",
                    "status": "queued",
                    "priority": 3,
                    "queued_at": base_now - 5.0,
                    "queue_front_order": "order-keep",
                    "queue_front_rank": 2,
                    "full_synced_until_time": 1796000000,
                }
            ]
        )
        repo = JjcSyncRepo(db=db)
        history = FakeHistoryClient(
            [{"data": [{"match_id": 9004, "match_time": 1810000400, "pvpType": 3}]}]
        )
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        with patch("src.storage.mongo_repos.jjc_sync_repo.time.time", return_value=base_now), patch(
            "src.services.jx3.jjc_match_data_sync.time.time", return_value=base_now
        ), patch.object(JjcSyncRepo, "claim_match_detail", return_value=None), patch.object(
            JjcSyncRepo,
            "get_match_detail_sync_state",
            return_value={
                "exists": True,
                "status": "discovered",
                "action": "claimable",
                "terminal": False,
                "claimable": True,
            },
        ):
            tick = await service.worker_tick(mode="full", worker_id="worker-1")

        self.assertFalse(tick["processed"])
        self.assertTrue(tick["result"]["interrupted"])
        self.assertNotIn("retry_after", tick["result"])

        row = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(row["status"], "queued")
        self.assertIsNone(row["next_sync_after"])
        self.assertEqual(row["queued_at"], base_now)
        self.assertEqual(row["queue_front_order"], "order-keep")
        self.assertEqual(row["queue_front_rank"], 2)
        self.assertEqual(row["full_synced_until_time"], 1796000000)

    async def test_legacy_fake_repo_without_next_sync_after_falls_back_cleanly(self) -> None:
        base_now = 1800000000.0
        repo = FakeRepo()
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "global:legacy",
            "server": "梦江南",
            "name": "旧替身",
            "global_role_id": "SK01-LEGACY",
        }
        repo.detail_states[9005] = {
            "match_id": 9005,
            "status": "failed",
            "detail_retry_after": base_now + 600.0,
        }
        history = FakeHistoryClient(
            [{"data": [{"match_id": 9005, "match_time": 1810000500, "pvpType": 3}]}]
        )
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        with patch("src.services.jx3.jjc_match_data_sync.time.time", return_value=base_now):
            tick = await service.worker_tick(mode="full", worker_id="worker-1")

        self.assertFalse(tick["processed"])
        self.assertEqual(tick["result"]["retry_after"], base_now + 600.0)
        self.assertIsNotNone(repo.interrupted_release)
        assert repo.interrupted_release is not None
        self.assertEqual(repo.interrupted_release["identity_key"], "global:legacy")
        self.assertTrue(repo.interrupted_release["requeue"])


if __name__ == "__main__":
    unittest.main()
