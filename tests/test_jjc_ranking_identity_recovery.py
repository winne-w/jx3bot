"""Public service regressions: a parsed metric is not an identity proof."""

import copy
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.test_jjc_ranking_inspect import (
    DirectJjcRankingInspectService,
    FakeJjcInspectRepo,
    FakeRoleIdentityRepo,
    WarmupJjcRankingService,
)
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo


def identity_fixture():
    return {
        "_id": "identity-1", "identity_key": "global_id:123456",
        "global_id": "123456", "global_role_id": "SK01-target",
        "game_role_id": "200", "role_id": "200", "zone": "zone-a",
        "server": "server-a", "name": "target",
    }


def indicator_fixture(**role_info_overrides):
    role_info = {
        "role_id": "200", "global_role_id": "SK01-target",
        "server": "server-a", "zone": "zone-a", "role_name": "target",
        "name": "target",
    }
    role_info.update(role_info_overrides)
    return {"code": 0, "data": {
        "role_info": role_info,
        "indicator": [{"type": "3c", "total_count": 12, "score": 2200}],
    }}


class PublicIndicatorIdentitySafetyTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, raw):
        self.identity = identity_fixture()
        self.repo = FakeRoleIdentityRepo(self.identity)
        self.repo.get_by_id = AsyncMock(side_effect=lambda _: copy.deepcopy(self.identity))
        self.repo.replace_query_ids_if_unchanged = AsyncMock(return_value=False)
        self.cache = FakeJjcInspectRepo()
        self.kungfu = MagicMock()
        self.kungfu.upsert_role_identity_from_indicator = AsyncMock(
            side_effect=lambda **_: copy.deepcopy(self.identity)
        )
        self.fetch = MagicMock(return_value=raw)
        self.replay = MagicMock()
        return DirectJjcRankingInspectService(
            ranking_service=MagicMock(), kungfu_cache_repo=self.kungfu,
            match_history_client=MagicMock(), match_detail_client=MagicMock(),
            cache_repo=self.cache, tuilan_request=MagicMock(),
            role_indicator_fetcher=self.fetch, kungfu_pinyin_to_chinese={},
            role_identity_repo=self.repo, match_replay_client=self.replay,
        )

    async def query(self, service):
        return await service.get_role_indicator(
            server="server-a", name="target", identity_only=True,
            force_refresh=True,
        )

    async def test_r08_current_valid_id_does_not_probe_replay_or_replace_ids(self):
        service = self.make_service(indicator_fixture())
        result = await self.query(service)
        self.assertFalse(result.get("error"))
        self.assertEqual(self.fetch.call_count, 1)
        self.replay.get_match_replay.assert_not_called()
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()
        self.assertEqual(len(self.cache.saved_role_indicator), 1)

    async def test_r04_empty_role_info_is_not_a_successful_season_response(self):
        raw = indicator_fixture()
        raw["data"]["role_info"] = {}
        service = self.make_service(raw)
        result = await self.query(service)
        self.assertTrue(result.get("error"), "metrics without a role cannot prove target identity")
        self.assertEqual(self.cache.saved_role_indicator, [])
        self.kungfu.upsert_role_identity_from_indicator.assert_not_awaited()

    async def test_r04_empty_3c_does_not_cache_or_invent_zero_matches(self):
        raw = indicator_fixture()
        raw["data"]["indicator"] = [{"type": "3c"}]
        service = self.make_service(raw)
        result = await self.query(service)
        self.assertTrue(result.get("error"))
        self.assertEqual(self.cache.saved_role_indicator, [])
        self.assertNotIn("indicator", result)

    async def test_r06_mismatched_response_is_not_cached_under_the_target(self):
        for override in (
            {"role_id": "999"}, {"zone": "zone-b"},
            {"server": "server-b"}, {"global_role_id": "SK01-other"},
        ):
            with self.subTest(override=override):
                service = self.make_service(indicator_fixture(**override))
                result = await self.query(service)
                self.assertTrue(result.get("error"), "a valid metric for another role is not target success")
                self.assertEqual(self.cache.saved_role_indicator, [])
                self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r09_identity_changed_during_request_does_not_cache_old_success(self):
        service = self.make_service(indicator_fixture())

        def concurrent_transfer(*args, **kwargs):
            self.identity["game_role_id"] = "300"
            self.identity["role_id"] = "300"
            self.identity["server"] = "server-b"
            return indicator_fixture()

        self.fetch.side_effect = concurrent_transfer
        result = await self.query(service)
        self.assertTrue(result.get("error"), "must reread a changed identity before publishing its cache")
        self.assertEqual(self.cache.saved_role_indicator, [])

    async def test_r28_missing_identity_never_creates_a_recovery_target(self):
        service = self.make_service(indicator_fixture())
        self.repo.identity = None
        result = await self.query(service)
        self.assertEqual(result.get("message"), "role_identity_not_found")
        self.fetch.assert_not_called()
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r18_fresh_cache_hit_does_not_probe(self):
        service = self.make_service(indicator_fixture())
        self.cache.role_indicator_cache[self.identity["identity_key"]] = {
            "indicator": {"total_matches": 12}, "raw": indicator_fixture(),
        }
        result = await service.get_role_indicator(
            server="server-a", name="target", identity_only=True,
        )
        self.assertTrue(result["cache"]["hit"])
        self.fetch.assert_not_called()
        self.replay.get_match_replay.assert_not_called()

    def prepare_recovery(self, service):
        self.identity.update(game_role_id="100", role_id="100")
        self.kungfu.load_query_id_recovery_candidates = AsyncMock(return_value=[{
            "role_id": "200", "zone": "zone-a", "server": "server-a", "match_id": 700,
        }])
        self.fetch.side_effect = lambda role_id, *args, **kwargs: (
            {"code": 0, "data": {"role_info": {}, "indicator": []}}
            if role_id == "100" else indicator_fixture()
        )
        self.replay.get_match_replay.return_value = {"code": 0, "data": {"players": [
            {"role_id": "200", "global_role_id": "123456", "role_name": "target"},
        ]}}

        async def publish(*args, **kwargs):
            self.identity.update(game_role_id="200", role_id="200")
            return True

        self.repo.replace_query_ids_if_unchanged.side_effect = publish

    async def test_r28_default_off_does_not_probe_or_publish_recovery(self):
        service = self.make_service(indicator_fixture())
        self.prepare_recovery(service)
        with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 0):
            result = await self.query(service)
        self.assertTrue(result.get("error"))
        self.kungfu.load_query_id_recovery_candidates.assert_not_awaited()
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_r28_enabled_recovery_returns_and_caches_only_validated_response(self):
        service = self.make_service(indicator_fixture())
        self.prepare_recovery(service)
        with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 1):
            result = await self.query(service)
        self.assertFalse(result.get("error"), result)
        self.assertEqual(result["identity"]["game_role_id"], "200")
        self.assertEqual(self.fetch.call_count, 2)
        self.repo.replace_query_ids_if_unchanged.assert_awaited_once()
        self.assertEqual(self.cache.saved_role_indicator[0][1]["game_role_id"], "200")

    async def test_r16_cache_failure_does_not_rollback_a_verified_id_or_claim_success(self):
        service = self.make_service(indicator_fixture())
        self.prepare_recovery(service)
        self.cache.save_role_indicator = AsyncMock(side_effect=RuntimeError("cache down"))
        with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 1):
            result = await self.query(service)
        self.assertTrue(result.get("error"))
        self.assertEqual(result["message"], "indicator_cache_write_failed")
        self.assertEqual(self.identity["game_role_id"], "200")
        self.repo.replace_query_ids_if_unchanged.assert_awaited_once()

    async def test_r18_same_role_concurrent_force_refreshes_share_one_recovery(self):
        service = self.make_service(indicator_fixture())
        self.prepare_recovery(service)
        with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 1):
            results = await asyncio.gather(*(self.query(service) for _ in range(8)))
        self.assertTrue(all(not result.get("error") for result in results), results)
        self.assertEqual(self.fetch.call_count, 2)
        self.repo.replace_query_ids_if_unchanged.assert_awaited_once()

    async def test_r18_force_refresh_does_not_bypass_failed_recovery_cooldown(self):
        service = self.make_service({"code": 0, "data": {"role_info": {}, "indicator": []}})
        self.kungfu.load_query_id_recovery_candidates = AsyncMock(return_value=[])
        with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 1):
            first = await self.query(service)
            second = await self.query(service)
        self.assertTrue(first.get("error"))
        self.assertEqual(first, second)
        self.assertEqual(self.fetch.call_count, 1)

    async def test_busy_healthy_role_can_retry_immediately_after_other_http_finishes(self):
        first_helper = PublicIndicatorIdentitySafetyTests()
        first_service = first_helper.make_service(indicator_fixture())
        service = self.make_service(indicator_fixture(global_role_id="SK01-other", name="other"))
        self.identity.update(name="other", global_id="654321", global_role_id="SK01-other")
        self.kungfu.load_query_id_recovery_candidates = AsyncMock(return_value=[])
        first_helper.kungfu.load_query_id_recovery_candidates = AsyncMock(return_value=[])
        entered = threading.Event()
        release = threading.Event()
        counts = {"running": 0, "maximum": 0}
        guard = threading.Lock()

        def track_fetch(*args, blocked=False, **kwargs):
            with guard:
                counts["running"] += 1
                counts["maximum"] = max(counts["maximum"], counts["running"])
            try:
                if blocked:
                    entered.set()
                    release.wait(2)
                    return indicator_fixture()
                return indicator_fixture(global_role_id="SK01-other", name="other")
            finally:
                with guard:
                    counts["running"] -= 1

        first_helper.fetch.side_effect = lambda *a, **kw: track_fetch(*a, blocked=True, **kw)
        self.fetch.side_effect = track_fetch
        with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 1):
            pending = asyncio.create_task(first_helper.query(first_service))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.001)
                self.assertTrue(entered.is_set())
                busy = await service.get_role_indicator(server="server-a", name="other", identity_only=True, force_refresh=True)
                self.fetch.assert_not_called()
            finally:
                release.set()
            self.assertFalse((await pending).get("error"))
            retried = await service.get_role_indicator(server="server-a", name="other", identity_only=True, force_refresh=True)
        self.assertFalse(retried.get("error"), "transient global permit contention must not poison role cooldown")
        self.assertEqual(busy.get("message"), "indicator_recovery_busy")
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(counts["maximum"], 1)

    async def test_late_old_id_cache_write_cannot_poison_next_current_id_read(self):
        service = self.make_service(indicator_fixture(role_id="100"))
        self.identity.update(game_role_id="100", role_id="100")
        self.fetch.side_effect = lambda role_id, *args, **kwargs: indicator_fixture(role_id=role_id)
        save = self.cache.save_role_indicator

        async def write_after_concurrent_repair(key, payload):
            self.identity.update(game_role_id="200", role_id="200")
            await save(key, payload)

        self.cache.save_role_indicator = write_after_concurrent_repair
        self.assertFalse((await self.query(service)).get("error"))
        self.assertEqual(self.cache.role_indicator_cache[self.identity["identity_key"]]["game_role_id"], "100")
        result = await service.get_role_indicator(server="server-a", name="target", identity_only=True)
        self.assertFalse(result.get("error"), result)
        self.assertFalse(result["cache"]["hit"], "stale save after ID CAS must be a cache miss")
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(result["raw"]["data"]["role_info"]["role_id"], "200")

    async def test_explicit_cache_identity_conflicts_are_misses_not_renewed_metrics(self):
        for conflicting in (
            {"game_role_id": "100"}, {"role_id": "100"}, {"zone": "zone-b"},
            {"server": "server-b"}, {"global_id": "999"}, {"global_role_id": "SK01-other"},
            {"raw": indicator_fixture(role_id="100")},
            {"raw": indicator_fixture(global_role_id="SK01-other")},
        ):
            with self.subTest(conflicting=conflicting):
                service = self.make_service(indicator_fixture())
                self.cache.role_indicator_cache[self.identity["identity_key"]] = dict(
                    {"indicator": {"total_matches": 999}, "raw": indicator_fixture()}, **conflicting,
                )
                result = await service.get_role_indicator(server="server-a", name="target", identity_only=True)
                self.assertFalse(result.get("error"), result)
                self.assertFalse(result["cache"]["hit"])
                self.assertEqual(result["indicator"]["total_matches"], 12)
                self.assertEqual(self.fetch.call_count, 1)

    async def test_legacy_cache_missing_identity_fields_remains_compatible(self):
        service = self.make_service(indicator_fixture())
        self.cache.role_indicator_cache[self.identity["identity_key"]] = {"indicator": {"total_matches": 12}}
        result = await service.get_role_indicator(server="server-a", name="target", identity_only=True)
        self.assertTrue(result["cache"]["hit"])
        self.fetch.assert_not_called()


class RecoveryPublicationConfigTests(unittest.TestCase):
    def load_config(self, *, runtime=None, environment=None):
        path = Path(__file__).resolve().parents[1] / "config.py"
        with tempfile.TemporaryDirectory() as directory:
            if runtime is not None:
                (Path(directory) / "runtime_config.json").write_text(json.dumps(runtime))
            previous = os.getcwd()
            try:
                os.chdir(directory)
                with patch.dict(os.environ, environment or {}, clear=True):
                    return runpy.run_path(str(path))
            finally:
                os.chdir(previous)

    def test_r28_automatic_recovery_is_disabled_by_default(self):
        config = self.load_config()
        self.assertIn("JJC_ROLE_IDENTITY_RECOVERY_ENABLED", config)
        self.assertEqual(config["JJC_ROLE_IDENTITY_RECOVERY_ENABLED"], 0)

    def test_r28_explicit_environment_and_runtime_config_can_enable_it(self):
        key = "JJC_ROLE_IDENTITY_RECOVERY_ENABLED"
        self.assertEqual(self.load_config(environment={key: "1"}).get(key), 1)
        self.assertEqual(self.load_config(runtime={key: 1}).get(key), 1)
        self.assertEqual(self.load_config(runtime={key: 0}, environment={key: "1"}).get(key), 0)


class PersistedIndicatorIdentityReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_loader_preserves_stored_numeric_identity_and_legacy_role_id_for_guard(self):
        db = MagicMock()
        db.jjc_role_indicator.find_one = AsyncMock(return_value={
            "cache_key": "global_id:123456", "identity_key": "global_id:123456",
            "global_id": "999999", "role_id": "100", "cached_at": time.time(),
            "indicator": {"total_matches": 12},
        })
        loaded = await JjcInspectRepo(db=db).load_role_indicator("global_id:123456")
        self.assertEqual(loaded.get("global_id"), "999999")
        self.assertEqual(loaded.get("role_id"), "100")
        self.assertFalse(DirectJjcRankingInspectService._cached_indicator_matches_identity(identity_fixture(), loaded))
        db.jjc_role_indicator.update_one.assert_not_called()

    async def test_real_loader_missing_legacy_fields_remains_read_compatible(self):
        db = MagicMock()
        db.jjc_role_indicator.find_one = AsyncMock(return_value={
            "cache_key": "global_id:123456", "cached_at": time.time(),
            "indicator": {"total_matches": 12},
        })
        loaded = await JjcInspectRepo(db=db).load_role_indicator("global_id:123456")
        self.assertIsNone(loaded.get("global_id"))
        self.assertIsNone(loaded.get("role_id"))
        self.assertTrue(DirectJjcRankingInspectService._cached_indicator_matches_identity(identity_fixture(), loaded))


class RecoveryRequestIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_singleflight_never_merges_different_request_semantics(self):
        for first, second in (
            ({"identity_only": False}, {"identity_only": True}),
            ({"global_id": "111"}, {"global_id": "222"}),
            ({"force_refresh": False}, {"force_refresh": True}),
        ):
            with self.subTest(first=first, second=second):
                service = PublicIndicatorIdentitySafetyTests().make_service(indicator_fixture())

                async def result_for(**kwargs):
                    await asyncio.sleep(0.01)
                    return {"requested": kwargs}

                once = AsyncMock(side_effect=result_for)
                with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 1), patch.object(
                    DirectJjcRankingInspectService, "_get_role_indicator_once", once,
                ):
                    results = await asyncio.gather(
                        service.get_role_indicator(server="server-a", name="target", **first),
                        service.get_role_indicator(server="server-a", name="target", **second),
                    )
                self.assertEqual(once.await_count, 2)
                for key, value in second.items():
                    self.assertEqual(results[1]["requested"][key], value)

    async def test_failed_nonlocal_request_cooldown_does_not_pollute_identity_only(self):
        service = PublicIndicatorIdentitySafetyTests().make_service(indicator_fixture())
        once = AsyncMock(side_effect=[{"error": True, "message": "upstream_failed"}, {"ok": True}])
        with patch("config.JJC_ROLE_IDENTITY_RECOVERY_ENABLED", 1), patch.object(
            DirectJjcRankingInspectService, "_get_role_indicator_once", once,
        ):
            await service.get_role_indicator(server="server-a", name="target", identity_only=False)
            result = await service.get_role_indicator(server="server-a", name="target", identity_only=True)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(once.await_count, 2)


class RankingWarmupIdentitySafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_r20_ranking_checks_current_then_reuses_candidate_and_independent_replay(self):
        identity = identity_fixture()
        identity.update(game_role_id="100", role_id="100")
        identities = MagicMock()
        identities.resolve_best_identity_with_id = AsyncMock(return_value=identity)
        identities.replace_query_ids_if_unchanged = AsyncMock(return_value=True)
        cache = MagicMock()
        cache._get_identity_repo.return_value = identities
        cache.load_query_id_recovery_candidates = AsyncMock(return_value=[])
        request = MagicMock(return_value={"code": 0, "data": {"players": [
            {"global_role_id": "123456", "role_id": "200", "role_name": "target"},
        ]}})
        service = WarmupJjcRankingService(MagicMock(), tuilan_request=request, match_replay_url="replay-url")
        with patch.object(WarmupJjcRankingService, "_cache", return_value=cache), patch(
            "src.services.jx3.jjc_ranking.get_role_indicator",
            return_value={"code": 0, "data": {"role_info": {}, "indicator": []}},
        ) as indicator_fetch:
            result = await service._recover_ranking_query_ids(
                server="server-a", name="target", role_indicator={
                    "global_id": "123456", "game_role_id": "200", "role_id": "200",
                    "zone": "zone-a", "raw": indicator_fixture(),
                    "request_started_at": datetime.now(timezone.utc),
                }, cache_warmup={"match_detail": {"match_id": 700}},
            )
        self.assertTrue(result)
        indicator_fetch.assert_called_once_with("100", "zone-a", "server-a", tuilan_request=request, name="target")
        request.assert_called_once_with("replay-url", {"match_id": 700})
        identities.replace_query_ids_if_unchanged.assert_awaited_once()

    async def test_r07_r20_ranking_hints_do_not_authorize_mismatched_raw_response(self):
        repo = MagicMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_role_recent = AsyncMock()
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", repo)
        await service._warmup_inspect_cache_from_kungfu_detail(
            server="server-a", name="target", kungfu_detail={"_cache_warmup": {
                "role_indicator": {
                    "source": "indicator", "global_id": "123456",
                    "game_role_id": "200", "role_id": "200", "zone": "zone-a",
                    "global_role_id": "SK01-target", "raw": indicator_fixture(role_id="999"),
                },
            }},
        )
        repo.save_role_indicator.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
