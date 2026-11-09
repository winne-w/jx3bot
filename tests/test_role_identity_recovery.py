"""Behavioral contract for the small, dependency-injected recovery functions."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone
import importlib
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock


def old_identity(global_id="123456"):
    return {
        "_id": "identity-" + global_id, "identity_key": "global_id:" + global_id,
        "global_id": global_id, "global_role_id": "SK01-" + global_id,
        "game_role_id": "100", "role_id": "100", "zone": "zone-a",
        "server": "server-a", "name": "target", "latest_match_time": 1700000000,
    }


def candidate(role_id="200", **extra):
    return dict({"role_id": role_id, "zone": "zone-a", "server": "server-a", "match_id": 700}, **extra)


def raw_indicator(role_id="200", global_id="123456", **extra):
    info = {"role_id": role_id, "global_role_id": "SK01-" + global_id,
            "zone": "zone-a", "server": "server-a", "name": "target"}
    info.update(extra)
    return {"code": 0, "data": {"role_info": info,
            "indicator": [{"type": "3c", "total_count": 12, "score": 2200}]}}


def raw_replay(role_id="200", global_id="123456"):
    return {"code": 0, "data": {"players": [
        {"role_id": role_id, "global_role_id": global_id,
         "server": "server-a", "zone": "zone-a", "role_name": "target"},
    ]}}


EMPTY = {"code": 0, "data": {"role_info": {}, "indicator": []}}


class RecoveryFunctionContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Import in setUp keeps collection working during the first Red step.
        self.module = importlib.import_module("src.services.jx3.role_identity_recovery")
        self.identity = old_identity()
        self.repo = MagicMock()
        self.repo.replace_query_ids_if_unchanged = AsyncMock(return_value=True)
        self.repo.get_by_id = AsyncMock(return_value=dict(self.identity, game_role_id="200", role_id="200"))
        self.indicator_calls = []
        self.replay_calls = []

    def fetch_indicator(self, *, role_id, zone, server):
        self.indicator_calls.append((role_id, zone, server))
        return copy.deepcopy(EMPTY if role_id == "100" else raw_indicator(role_id))

    def fetch_replay(self, *, match_id):
        self.replay_calls.append(match_id)
        return raw_replay()

    async def recover(self, **overrides):
        kwargs = {
            "identity_repo": self.repo, "candidates": [candidate()],
            "indicator_fetcher": self.fetch_indicator,
            "replay_fetcher": self.fetch_replay,
        }
        kwargs.update(overrides)
        return await self.module.recover_query_ids(self.identity, **kwargs)

    async def test_r08_current_success_is_healthy_without_replay_or_write(self):
        self.identity.update(game_role_id="200", role_id="200")
        result = await self.recover(candidates=[candidate("50")], publish=True)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(len(self.indicator_calls), 1)
        self.assertEqual(self.replay_calls, [])
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r03_verify_returns_raw_proof_but_never_writes(self):
        result = await self.recover(publish=False)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["candidate"]["role_id"], "200")
        self.assertEqual(result["raw"], raw_indicator())
        self.assertEqual(result["replay_data"], raw_replay())
        self.assertIsInstance(result["observed_at"], datetime)
        self.assertIsNotNone(result["observed_at"].tzinfo)
        self.assertEqual(result["observed_at"].microsecond % 1000, 0)
        self.assertLessEqual(result["logical_calls"], 5)
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r03_publish_uses_exact_original_snapshot_and_validated_id(self):
        before = copy.deepcopy(self.identity)
        result = await self.recover(publish=True)
        self.assertEqual(result["status"], "recovered")
        self.repo.replace_query_ids_if_unchanged.assert_awaited_once()
        args, kwargs = self.repo.replace_query_ids_if_unchanged.await_args
        self.assertEqual(args[0], before)
        self.assertEqual(kwargs["game_role_id"], "200")
        self.assertEqual(kwargs["role_id"], "200")
        self.assertEqual(self.identity, before)

    async def test_r09_cas_conflict_is_not_recovered_and_does_not_retry_forcefully(self):
        self.repo.replace_query_ids_if_unchanged.return_value = False
        result = await self.recover(publish=True)
        self.assertEqual(result["status"], "conflict")
        self.repo.replace_query_ids_if_unchanged.assert_awaited_once()
        self.repo.get_by_id.assert_awaited()

    async def test_r05_same_name_or_copied_cache_key_cannot_replace_exact_numeric_mapping(self):
        wrong = raw_replay(global_id="999999")
        wrong["data"]["players"][0]["global_id"] = self.identity["global_id"]
        wrong["data"]["players"][0]["identity_key"] = self.identity["identity_key"]
        result = await self.recover(replay_data=wrong, publish=True)
        self.assertNotIn(result["status"], {"ready", "recovered"})
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r06_response_mismatch_and_changed_sk01_are_not_published(self):
        for extra in ({"server": "server-b"}, {"zone": "zone-b"},
                      {"role_id": "999"}, {"global_role_id": "SK01-other"}):
            with self.subTest(extra=extra):
                fetch = lambda **kw: EMPTY if kw["role_id"] == "100" else raw_indicator(**extra)
                result = await self.recover(indicator_fetcher=fetch, publish=True)
                self.assertNotIn(result["status"], {"ready", "recovered"})
                self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r04_no_3c_does_not_turn_a_real_empty_result_into_zero_matches(self):
        empty_metrics = raw_indicator()
        empty_metrics["data"]["indicator"] = [{"type": "3c"}]
        result = await self.recover(indicator_fetcher=lambda **_: empty_metrics, publish=True)
        self.assertNotIn(result["status"], {"ready", "recovered", "healthy"})
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r19_auth_and_429_stop_without_trying_candidates(self):
        for raw in ({"code": 401, "msg": "unauthorized"},
                    {"code": 429, "msg": "too many requests"}):
            with self.subTest(raw=raw):
                fetch = MagicMock(return_value=raw)
                result = await self.recover(indicator_fetcher=fetch, publish=True)
                self.assertEqual(result["status"], "upstream_error")
                self.assertEqual(fetch.call_count, 1)
                self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r19_network_exception_is_not_evidence_of_an_obsolete_id(self):
        fetch = MagicMock(side_effect=TimeoutError("upstream timeout"))
        result = await self.recover(indicator_fetcher=fetch, publish=True)
        self.assertEqual(result["status"], "upstream_error")
        self.assertEqual(fetch.call_count, 1)
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r19_only_two_alternative_indicators_and_at_most_five_calls(self):
        fetch = MagicMock(return_value=EMPTY)
        result = await self.recover(
            indicator_fetcher=fetch,
            candidates=[candidate(str(n)) for n in range(200, 250)], publish=True,
        )
        self.assertLessEqual(fetch.call_count, 3)
        self.assertLessEqual(result["logical_calls"], 5)
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_recovery_filters_out_of_scope_locators_before_candidate_budget(self):
        result = await self.recover(candidates=[
            dict(candidate("900"), server="historical-server"),
            dict(candidate("901"), zone="historical-zone"),
            candidate("200"),
        ], publish=False)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.indicator_calls, [
            ("100", "zone-a", "server-a"), ("200", "zone-a", "server-a"),
        ])

    async def test_upstream_failures_retain_endpoint_and_original_status_for_caller(self):
        for endpoint in ("indicator", "history", "replay"):
            for code in (401, 403, 429):
                with self.subTest(endpoint=endpoint, code=code):
                    failure = {"code": code, "msg": "upstream refusal"}
                    options = {"publish": True}
                    if endpoint == "indicator":
                        options["indicator_fetcher"] = lambda **kw: EMPTY if kw["role_id"] == "100" else failure
                    elif endpoint == "history":
                        options["candidates"] = [{key: value for key, value in candidate().items() if key != "match_id"}]
                        options["history_fetcher"] = lambda **_: failure
                    else:
                        options["replay_fetcher"] = lambda **_: failure
                    result = await self.recover(**options)
                    self.assertEqual(result["status"], "upstream_error")
                    self.assertEqual(result.get("upstream_endpoint"), endpoint)
                    self.assertEqual(result.get("upstream_error_data"), failure)
                    self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r19_respects_a_smaller_remaining_operation_budget(self):
        result = await self.recover(max_logical_calls=1, publish=True)
        self.assertEqual(len(self.indicator_calls), 1)
        self.assertEqual(self.replay_calls, [])
        self.assertLessEqual(result["logical_calls"], 1)
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r20_existing_raw_evidence_is_reused_not_refetched(self):
        result = await self.recover(
            current_indicator=EMPTY, replay_data=raw_replay(), publish=False,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.indicator_calls, [("200", "zone-a", "server-a")])
        self.assertEqual(self.replay_calls, [])
        self.assertEqual(result["logical_calls"], 1)

    async def test_r20_candidate_raw_is_not_the_old_current_request_success(self):
        result = await self.recover(current_indicator=raw_indicator(), publish=False)
        self.assertNotEqual(result["status"], "healthy")

    async def test_r20_exact_candidate_request_reuses_raw_and_original_observation(self):
        observed = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=1)
        fetch = MagicMock(side_effect=lambda **kw: EMPTY if kw["role_id"] == "100" else
                          (_ for _ in ()).throw(AssertionError("must not refetch the held candidate")))
        result = await self.recover(
            current_indicator=raw_indicator(),
            current_indicator_request=dict(candidate(), observed_at=observed),
            indicator_fetcher=fetch, publish=False,
        )
        self.assertEqual(result["status"], "ready")
        fetch.assert_called_once_with(role_id="100", zone="zone-a", server="server-a")
        self.assertEqual(self.replay_calls, [700])
        self.assertEqual(result["logical_calls"], 2)
        self.assertEqual(result["observed_at"], observed)

    async def test_r08_held_alternative_does_not_replace_a_still_healthy_current_id(self):
        observed = datetime.now(timezone.utc)
        fetch = MagicMock(side_effect=lambda **kw: raw_indicator(role_id=kw["role_id"]))
        result = await self.recover(
            current_indicator=raw_indicator(),
            current_indicator_request=dict(candidate(), observed_at=observed),
            indicator_fetcher=fetch, publish=True,
        )
        self.assertEqual(result["status"], "healthy")
        fetch.assert_called_once_with(role_id="100", zone="zone-a", server="server-a")
        self.assertEqual(self.replay_calls, [])
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r20_request_mismatch_or_missing_stale_time_cannot_authorize_publish(self):
        fresh = datetime.now(timezone.utc)
        for request in (
            dict(candidate("999"), observed_at=fresh),
            dict(candidate(), zone="zone-b", observed_at=fresh),
            dict(candidate()),
            dict(candidate(), observed_at=fresh - timedelta(seconds=30)),
        ):
            with self.subTest(request=request):
                result = await self.recover(
                    current_indicator=raw_indicator(), current_indicator_request=request,
                    indicator_fetcher=lambda **_: EMPTY, publish=True,
                )
                self.assertNotIn(result["status"], {"ready", "recovered", "healthy"})
                self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r07_source_label_is_not_raw_indicator_authorization(self):
        forged = {"source": "indicator", "role_id": "200", "global_id": "123456",
                  "global_role_id": "SK01-123456", "total_matches": 12}
        result = await self.recover(
            current_indicator=forged, indicator_fetcher=lambda **_: forged, publish=True,
        )
        self.assertNotIn(result["status"], {"healthy", "ready", "recovered"})
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r17_all_distinct_locators_survive_newer_duplicate_evidence(self):
        candidates = self.module.collect_query_id_candidates(
            self.identity,
            [candidate("100", cached_at=300), candidate("200", cached_at=100)],
            [candidate("100", cached_at=400)],
        )
        locators = [(row["zone"], row["server"], str(row["role_id"])) for row in candidates]
        self.assertEqual(set(locators), {("zone-a", "server-a", "100"), ("zone-a", "server-a", "200")})
        self.assertEqual(len(locators), 2)

    async def test_r30_another_server_is_unresolved_not_a_partial_profile_migration(self):
        result = await self.recover(
            candidates=[dict(candidate(), server="server-b")], publish=True,
            indicator_fetcher=lambda **kw: EMPTY if kw["role_id"] == "100" else raw_indicator(server="server-b"),
            replay_data=raw_replay(),
        )
        self.assertNotIn(result["status"], {"ready", "recovered"})
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r29_timed_out_http_keeps_actual_inflight_permit_until_finished(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_fetch(**kwargs):
            calls.append(kwargs["role_id"])
            entered.set()
            release.wait(2)
            return raw_indicator(role_id=kwargs["role_id"])

        try:
            first = asyncio.create_task(self.recover(
                indicator_fetcher=slow_fetch, deadline_seconds=0.03, publish=True,
            ))
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.001)
            self.assertTrue(entered.is_set())
            result = await asyncio.wait_for(first, 0.5)
            self.assertNotIn(result["status"], {"ready", "recovered", "healthy"})
            other = old_identity("654321")
            second = await asyncio.wait_for(self.module.recover_query_ids(
                other, identity_repo=self.repo, candidates=[candidate()],
                indicator_fetcher=slow_fetch, replay_fetcher=self.fetch_replay,
                deadline_seconds=0.03, publish=True,
            ), 0.5)
            self.assertNotIn(second["status"], {"ready", "recovered", "healthy"})
            self.assertEqual(len(calls), 1, "await timeout must not release a still-running HTTP thread's permit")
        finally:
            release.set()
            await asyncio.sleep(0.05)
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
