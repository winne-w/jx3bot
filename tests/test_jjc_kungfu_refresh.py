"""Refresh orchestration and recoverable two-step publication, without Mongo/upstream."""
import asyncio
import copy
import unittest
from unittest.mock import AsyncMock, Mock

from bson import ObjectId

from src.infra.tuilan_kungfu_client import KungfuQueryError
from src.services.jx3.jjc_kungfu_policy import KungfuPolicy, make_scope
from src.services.jx3.jjc_kungfu_refresh import JjcKungfuRefreshService
from src.storage.mongo_repos.jjc_kungfu_refresh_repo import QueueIntegrityError
from tests.test_jjc_kungfu_classifier import indicator, metric, wins


class RefreshServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000.0
        self.policy = KungfuPolicy(make_scope("season-a", 100))
        self.identity = {"_id": ObjectId(), "server": "server-a", "zone": "zone-a",
                         "name": "role-a", "game_role_id": "id-a",
                         "global_role_id": "SK01-a", "updated_at": 10}
        self.task = {"_id": self.identity["_id"], "scope": self.policy.scope.copy(),
                     "status": "running", "generation": 7, "lease_token": "token-a",
                     "lease_expires_at": 1090, "consecutive_failures": 0}
        self.roles = Mock()
        self.roles.get_by_id = AsyncMock(side_effect=lambda _: copy.deepcopy(self.identity))
        self.roles.publish_jjc_kungfu_if_newer = AsyncMock(side_effect=self.publish)
        self.queue = Mock()
        self.queue.ensure_indexes = AsyncMock()
        self.queue.recover_expired = AsyncMock(return_value=0)
        self.queue.claim = AsyncMock(return_value=copy.deepcopy(self.task))
        self.queue.get_by_id = AsyncMock(side_effect=lambda _: copy.deepcopy(self.task))
        self.queue.complete = AsyncMock(return_value=True)
        self.client = Mock()
        self.client.attempt_timeout = 25
        self.client.query = AsyncMock(return_value={
            "indicator_data": indicator(metric("yunchang", 100)),
            "matches": wins(*(["bingxin"] * 10)), "requested_at": 999,
            "verified_at": 1000})
        self.service = JjcKungfuRefreshService(self.roles, self.queue, self.client,
            self.policy, {"bingxin": "冰心诀", "yunchang": "云裳心经"}, clock=lambda: self.now)

    async def publish(self, identity_id, locator, generation, result):
        if any((key in self.identity) != (key in locator) or self.identity.get(key) != locator.get(key)
               for key in ("server", "name", "zone", "game_role_id", "role_id", "global_id", "global_role_id")):
            return False
        old = self.identity.get("jjc_kungfu")
        if old is not None and old["publish_version"] >= generation:
            return False
        self.identity["jjc_kungfu"] = copy.deepcopy(result)
        return True

    def completion(self):
        return self.queue.complete.await_args

    async def test_concurrent_direct_calls_wait_before_reserving_a_role_lease(self):
        entered, release = asyncio.Event(), asyncio.Event()
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        async def query(*args, **kwargs):
            entered.set()
            await release.wait()
            return None
        from unittest.mock import patch
        with patch.object(self.service, "_execute", new=AsyncMock(side_effect=query)):
            first = asyncio.create_task(self.service.query_now(self.identity))
            await asyncio.wait_for(entered.wait(), 1)
            second = asyncio.create_task(self.service.query_now(self.identity))
            await asyncio.sleep(0.01)
            reservations_while_first_running = self.queue.claim_identity.await_count
            release.set()
            await asyncio.gather(first, second)
        self.assertEqual(reservations_while_first_running, 1)
        self.assertEqual(self.queue.claim_identity.await_count, 2)

    async def test_query_now_reserves_target_and_executes_directly_before_return(self):
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        result = await self.service.query_now(self.identity)
        self.assertEqual(result, self.identity["jjc_kungfu"])
        self.assertEqual(result["name"], "冰心诀")
        self.queue.register.assert_awaited_once()
        self.queue.claim_identity.assert_awaited_once_with(
            self.identity["_id"], self.policy.scope, self.now, lease_seconds=90)
        self.queue.claim.assert_not_awaited()
        self.client.query.assert_awaited_once()
        self.queue.complete.assert_awaited_once()

    async def test_query_now_failure_keeps_success_and_returns_none_with_error_code(self):
        self.identity["jjc_kungfu"] = {"publish_version": 6, "name": "云裳心经", "verified_at": 800}
        original = copy.deepcopy(self.identity["jjc_kungfu"])
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        self.client.query.side_effect = KungfuQueryError("request_timeout")
        self.assertIsNone(await self.service.query_now(self.identity))
        self.assertEqual(self.identity["jjc_kungfu"], original)
        self.assertEqual(self.completion().kwargs["error_code"], "request_timeout")

    async def test_query_now_queue_failure_does_not_return_an_unpersisted_query_value(self):
        self.queue.register = AsyncMock(side_effect=OSError("queue unavailable"))
        self.assertIsNone(await self.service.query_now(self.identity))
        self.client.query.assert_not_awaited()
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()

    async def test_query_now_cancellation_propagates_without_ack(self):
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        self.client.query.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.service.query_now(self.identity)
        self.queue.complete.assert_not_awaited()

    async def test_query_now_reservation_lost_or_cooldown_does_not_query(self):
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=None)
        self.assertIsNone(await self.service.query_now(self.identity))
        self.service.cooldown_until = self.now + 300
        self.assertIsNone(await self.service.query_now(self.identity))
        self.queue.register.assert_awaited_once()
        self.client.query.assert_not_awaited()

    async def test_query_now_rejects_changed_input_locator_before_query(self):
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        stale = dict(self.identity, game_role_id="stale-id")
        self.assertIsNone(await self.service.query_now(stale))
        self.client.query.assert_not_awaited()
        self.assertEqual(self.completion().kwargs["error_code"], "identity_changed")

    async def test_query_now_uncertain_publication_does_not_return_unpersisted_value(self):
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        self.roles.publish_jjc_kungfu_if_newer.side_effect = OSError("write failed")
        self.assertIsNone(await self.service.query_now(self.identity))
        self.assertNotIn("jjc_kungfu", self.identity)
        self.assertEqual(self.completion().kwargs["error_code"], "publication_unconfirmed")

    async def test_query_now_ack_exception_reads_back_saved_result_without_ack_retry(self):
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        self.queue.complete.side_effect = OSError("ack response lost")
        result = await self.service.query_now(self.identity)
        self.assertEqual(result, self.identity["jjc_kungfu"])
        self.assertEqual(result["publish_version"], self.task["generation"])
        self.queue.complete.assert_awaited_once()

    async def test_query_now_failed_persistence_readback_never_returns_other_version_or_scope(self):
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        for saved in ({"publish_version": 8, **self.policy.scope},
                      {"publish_version": 7, **self.policy.scope, "season_id": "other"}):
            self.roles.get_by_id.side_effect = [OSError("initial read failed"),
                                               {**self.identity, "jjc_kungfu": saved}]
            self.assertIsNone(await self.service.query_now(self.identity))
        self.client.query.assert_not_awaited()

    async def test_query_now_integrity_error_never_reads_back_preexisting_same_version_as_success(self):
        self.identity["jjc_kungfu"] = {**self.policy.scope, "publish_version": 7,
                                       "name": "云裳心经", "verified_at": 800}
        self.queue.register = AsyncMock()
        self.queue.claim_identity = AsyncMock(return_value=copy.deepcopy(self.task))
        self.assertIsNone(await self.service.query_now(self.identity))
        self.client.query.assert_not_awaited()
        self.roles.get_by_id.assert_awaited_once()
        self.queue.complete.assert_not_awaited()

    async def test_initialize_is_lazy_and_creates_queue_indexes(self):
        factory = Mock(return_value=self.policy)
        self.service.policy = factory
        factory.assert_not_called()
        await self.service.initialize()
        factory.assert_called_once_with()
        self.queue.ensure_indexes.assert_awaited_once()

    async def test_recovers_expired_before_claim_and_does_not_query_empty_queue(self):
        order = []
        self.queue.recover_expired.side_effect = lambda *a, **k: order.append("recover")
        self.queue.claim.side_effect = lambda *a, **k: order.append("claim")
        self.assertFalse(await self.service.run_once())
        self.assertEqual(order, ["recover", "claim"])
        self.client.query.assert_not_awaited()

    async def test_success_publishes_canonical_id_before_ack_and_preserves_identity_clock(self):
        async def complete(*args, **kwargs):
            self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 7)
            return True
        self.queue.complete.side_effect = complete
        self.assertTrue(await self.service.run_once())
        result = self.identity["jjc_kungfu"]
        self.assertEqual(result, {**self.policy.scope, "name": "冰心诀", "kungfu_id": 10081,
            "source": "match_history", "requested_at": 999, "verified_at": 1000,
            "win_sample_count": 10, "publish_version": 7})
        self.assertEqual(self.identity["updated_at"], 10)
        self.assertEqual(self.completion().args[2], 1000 + 21600)
        self.assertIsNone(self.completion().kwargs.get("error_code"))
        locator = self.roles.publish_jjc_kungfu_if_newer.await_args.args[1]
        self.assertNotIn("role_id", locator)
        self.assertNotIn("updated_at", locator)

    async def test_history_error_allows_indicator_fallback(self):
        self.client.query.return_value["matches"] = []
        self.client.query.return_value["history_error_code"] = "request_timeout"
        await self.service.run_once()
        result = self.identity["jjc_kungfu"]
        self.assertEqual((result["name"], result["kungfu_id"], result["source"]),
                         ("云裳心经", 10080, "indicator"))

    async def test_unknown_mapping_schedules_retry_without_replacing_success(self):
        old = {"publish_version": 6, "name": "云裳心经", "verified_at": 800}
        self.identity["jjc_kungfu"] = old.copy()
        self.client.query.return_value["indicator_data"] = indicator(metric("new-kungfu", 20))
        self.client.query.return_value["matches"] = []
        self.assertTrue(await self.service.run_once())
        self.assertEqual(self.identity["jjc_kungfu"], old)
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.assertEqual(self.completion().args[2], 1060)
        self.assertEqual(self.completion().kwargs["error_code"], "unknown_kungfu")

    async def test_missing_identity_does_not_query_or_upsert(self):
        self.roles.get_by_id.side_effect = None
        self.roles.get_by_id.return_value = None
        await self.service.run_once()
        self.client.query.assert_not_awaited()
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.assertEqual(self.completion().kwargs["error_code"], "identity_missing")

    async def test_query_failure_uses_capped_backoff_and_preserves_success(self):
        old = {"publish_version": 6, "verified_at": 800}
        self.identity["jjc_kungfu"] = old.copy()
        self.task["consecutive_failures"] = 100000
        self.queue.claim.return_value = copy.deepcopy(self.task)
        self.client.query.side_effect = KungfuQueryError("request_timeout")
        await self.service.run_once()
        self.assertEqual(self.identity["jjc_kungfu"], old)
        self.assertEqual(self.completion().args[2], 4600)

    async def test_auth_and_rate_limit_cool_down_consumer_without_claiming_other_tasks(self):
        for error, delay in ((KungfuQueryError("authentication_failed", auth=True), 300),
                             (KungfuQueryError("rate_limited", retry_after=400), 400),
                             (KungfuQueryError("rate_limited"), 300)):
            with self.subTest(code=error.code, retry=error.retry_after):
                self.service.cooldown_until = 0
                self.queue.claim.reset_mock()
                self.client.query.side_effect = error
                self.assertTrue(await self.service.run_once())
                self.assertEqual(self.completion().args[2], self.now + delay)
                self.assertFalse(await self.service.run_once())
                self.queue.claim.assert_awaited_once()
        self.now += 401
        self.assertTrue(await self.service.run_once())

    async def test_cancel_during_query_does_not_confirm_any_task(self):
        self.client.query.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.service.run_once()
        self.queue.complete.assert_not_awaited()
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()

    async def test_unknown_claim_response_does_not_issue_external_request(self):
        self.queue.claim.side_effect = OSError("unknown write outcome")
        with self.assertRaises(OSError):
            await self.service.run_once()
        self.client.query.assert_not_awaited()
        self.queue.complete.assert_not_awaited()

    async def test_role_read_failure_leaves_task_running(self):
        self.roles.get_by_id.side_effect = OSError("database unavailable")
        with self.assertRaises(OSError):
            await self.service.run_once()
        self.client.query.assert_not_awaited()
        self.queue.complete.assert_not_awaited()

    async def test_publish_unknown_but_readback_same_version_scope_confirms_saved_result(self):
        async def ambiguous(*args):
            await self.publish(*args)
            raise OSError("response lost")
        self.roles.publish_jjc_kungfu_if_newer.side_effect = ambiguous
        self.assertTrue(await self.service.run_once())
        self.queue.complete.assert_awaited_once()
        self.assertIsNone(self.completion().kwargs.get("error_code"))

    async def test_publish_unknown_and_readback_failure_leaves_running(self):
        self.roles.get_by_id.side_effect = [copy.deepcopy(self.identity), OSError("read failed")]
        self.roles.publish_jjc_kungfu_if_newer.side_effect = OSError("unknown")
        with self.assertRaises(OSError):
            await self.service.run_once()
        self.queue.complete.assert_not_awaited()

    async def test_publish_unknown_with_no_saved_result_is_not_acknowledged_successfully(self):
        self.roles.publish_jjc_kungfu_if_newer.side_effect = OSError("unknown")
        await self.service.run_once()
        self.assertEqual(self.completion().kwargs["error_code"], "publication_unconfirmed")

    async def test_publish_unknown_readback_same_generation_different_scope_is_not_success(self):
        self.identity["jjc_kungfu"] = {"publish_version": 6}
        async def ambiguous(*args):
            self.identity["jjc_kungfu"] = {"publish_version": 7, **self.policy.scope,
                                          "season_id": "old-season"}
            raise OSError("unknown")
        self.roles.publish_jjc_kungfu_if_newer.side_effect = ambiguous
        await self.service.run_once()
        self.assertEqual(self.completion().kwargs["error_code"], "publication_unconfirmed")

    async def test_ack_error_preserves_published_result_and_leaves_running(self):
        self.queue.complete.side_effect = OSError("ack unknown")
        with self.assertRaises(OSError):
            await self.service.run_once()
        self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 7)
        self.queue.complete.assert_awaited_once()

    async def test_ack_lost_token_does_not_revoke_published_value(self):
        self.queue.complete.return_value = False
        self.assertTrue(await self.service.run_once())
        self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 7)
        self.queue.complete.assert_awaited_once()

    async def test_old_worker_superseded_during_publish_cannot_override_new_value(self):
        newer = {"publish_version": 8, **self.policy.scope, "name": "云裳心经"}
        async def superseded(*args):
            self.identity["jjc_kungfu"] = newer.copy()
            return False
        self.roles.publish_jjc_kungfu_if_newer.side_effect = superseded
        await self.service.run_once()
        self.assertEqual(self.identity["jjc_kungfu"], newer)
        self.assertEqual(self.completion().kwargs["error_code"], "superseded")

    async def test_locator_change_rejects_result_and_schedules_retry(self):
        async def changed(*args):
            self.identity["game_role_id"] = "recovered-id"
            return await self.publish(*args)
        self.roles.publish_jjc_kungfu_if_newer.side_effect = changed
        await self.service.run_once()
        self.assertNotIn("jjc_kungfu", self.identity)
        self.assertEqual(self.completion().kwargs["error_code"], "identity_changed")

    async def test_malformed_existing_result_is_not_silently_repaired(self):
        self.identity["jjc_kungfu"] = {"name": "legacy-value-without-version"}
        await self.service.run_once()
        self.client.query.assert_not_awaited()
        self.assertEqual(self.completion().kwargs["error_code"], "invalid_publication_schema")

    async def test_explicit_lost_lease_before_publish_does_not_write_or_ack(self):
        self.queue.get_by_id.return_value = None
        self.queue.get_by_id.side_effect = None
        self.assertTrue(await self.service.run_once())
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.queue.complete.assert_not_awaited()

    async def test_scope_changed_in_process_during_query_does_not_publish(self):
        current = [self.policy]
        self.service.policy = lambda: current[0]
        async def query(*args):
            current[0] = KungfuPolicy(make_scope("season-b", 200))
            return self.client.query.return_value
        self.client.query.side_effect = query
        await self.service.run_once()
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.queue.complete.assert_not_awaited()

    async def test_invalid_query_timestamp_never_publishes_future_data(self):
        self.client.query.return_value["requested_at"] = 1001
        await self.service.run_once()
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.assertEqual(self.completion().kwargs["error_code"], "invalid_query_time")

    async def test_invalid_lease_budget_is_rejected_only_on_initialize(self):
        self.client.attempt_timeout = 100
        with self.assertRaises(ValueError):
            await self.service.initialize()
        self.queue.ensure_indexes.assert_not_awaited()

    async def test_read_failure_in_prepublication_check_leaves_running(self):
        self.queue.get_by_id.side_effect = OSError("ownership unknown")
        with self.assertRaises(OSError):
            await self.service.run_once()
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.queue.complete.assert_not_awaited()

    async def test_old_lease_token_before_publish_cannot_ack_new_worker(self):
        self.task["lease_token"] = "token-b"
        await self.service.run_once()
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.queue.complete.assert_not_awaited()

    async def test_cancel_before_publication_leaves_old_success_unchanged(self):
        old = {"publish_version": 6, "name": "云裳心经", "verified_at": 800}
        self.identity["jjc_kungfu"] = old.copy()
        self.queue.get_by_id.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.service.run_once()
        self.assertEqual(self.identity["jjc_kungfu"], old)
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.queue.complete.assert_not_awaited()

    async def test_cancel_after_role_write_preserves_result_without_ack(self):
        async def cancel_after_write(*args):
            await self.publish(*args)
            raise asyncio.CancelledError
        self.roles.publish_jjc_kungfu_if_newer.side_effect = cancel_after_write
        with self.assertRaises(asyncio.CancelledError):
            await self.service.run_once()
        self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 7)
        self.queue.complete.assert_not_awaited()

    async def test_cancel_during_ack_leaves_published_value_and_does_not_retry_ack(self):
        self.queue.complete.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.service.run_once()
        self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 7)
        self.queue.complete.assert_awaited_once()

    async def test_after_ack_failure_recovery_queries_again_and_publishes_higher_version(self):
        self.queue.complete.side_effect = OSError("ack unknown")
        with self.assertRaises(OSError):
            await self.service.run_once()
        self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 7)
        self.now += 91
        self.task.update(generation=8, lease_token="token-b", lease_expires_at=self.now + 90)
        self.queue.claim.return_value = copy.deepcopy(self.task)
        self.queue.complete.side_effect = None
        self.client.query.return_value["requested_at"] = self.now
        self.assertTrue(await self.service.run_once())
        self.assertEqual(self.client.query.await_count, 2)
        self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 8)
        self.assertEqual(self.completion().args[2], self.now + self.policy.refresh_seconds)

    async def test_null_locator_is_preserved_in_exact_publication_guard(self):
        self.identity["global_id"] = None
        await self.service.run_once()
        locator = self.roles.publish_jjc_kungfu_if_newer.await_args.args[1]
        self.assertIn("global_id", locator)
        self.assertIsNone(locator["global_id"])

    async def test_same_version_readback_after_false_conditional_write_can_ack(self):
        async def already_saved(*args):
            await self.publish(*args)
            return False
        self.roles.publish_jjc_kungfu_if_newer.side_effect = already_saved
        self.assertTrue(await self.service.run_once())
        self.assertIsNone(self.completion().kwargs.get("error_code"))

    async def test_typed_identity_conflict_does_not_publish_or_change_role(self):
        self.client.query.side_effect = KungfuQueryError("identity_mismatch")
        await self.service.run_once()
        self.assertNotIn("jjc_kungfu", self.identity)
        self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
        self.assertEqual(self.completion().kwargs["error_code"], "identity_mismatch")

    async def test_preexisting_same_or_higher_publication_is_queue_corruption_not_retry(self):
        for version in (7, 8, 7000):
            with self.subTest(published_version=version):
                self.identity["jjc_kungfu"] = {
                    **self.policy.scope, "publish_version": version,
                    "name": "冰心诀", "kungfu_id": 10081,
                    "requested_at": 900, "verified_at": 901,
                }
                with self.assertRaises(QueueIntegrityError):
                    await self.service.run_once()
                self.client.query.assert_not_awaited()
                self.roles.publish_jjc_kungfu_if_newer.assert_not_awaited()
                self.queue.complete.assert_not_awaited()
                self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], version)

    async def test_bson_long_counter_is_valid_and_still_enforces_regression(self):
        from bson.int64 import Int64
        self.task["generation"] = Int64(7)
        self.identity["jjc_kungfu"] = {"publish_version": Int64(6)}
        self.assertTrue(await self.service.run_once())
        self.assertEqual(self.identity["jjc_kungfu"]["publish_version"], 7)
