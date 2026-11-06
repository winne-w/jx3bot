"""Ranking uses valid cached attributes and directly queries each cache miss."""
import copy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.jjc_kungfu_policy import KungfuPolicy, make_scope
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo
from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo

NOW = 2000000000.0
SCOPE = make_scope("season-a", 1000)


def player(index):
    return {"personInfo": {"server": "server-a", "roleName": "role-%s" % index,
                           "gameRoleId": "id-%s" % index, "zone": "zone-a"},
            "score": 2200 - index}


def identity(index, age=1.0, name="冰心诀", include_result=True):
    doc = {"_id": ObjectId(), "identity_key": "game:zone-a:id-%s" % index,
           "server": "server-a", "name": "role-%s" % index,
           "zone": "zone-a", "game_role_id": "id-%s" % index,
           "role_id": "id-%s" % index}
    if include_result:
        doc["jjc_kungfu"] = dict(SCOPE, name=name,
            kungfu_id=10081 if name == "冰心诀" else 10080,
            source="indicator", requested_at=NOW-age-1,
            verified_at=NOW-age, publish_version=1, win_sample_count=0)
    return doc


class RankingKungfuCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.identities = SimpleNamespace(resolve_ranking_identities_batch=AsyncMock())
        self.queue = SimpleNamespace(register=AsyncMock())
        self.direct = SimpleNamespace(query_now=AsyncMock(return_value=None))
        self.policy = KungfuPolicy(SCOPE, refresh_seconds=100, max_stale_seconds=300,
                                   track_seconds=500)
        self.service = JjcRankingService(
            token="", ticket="", jjc_query_url="", arena_time_tag_url="",
            arena_ranking_url="", match_detail_url="", jjc_ranking_cache_duration=3600,
            kungfu_cache_duration=3600, current_season="season-a",
            current_season_start="1970-01-01", kungfu_healer_list=["云裳心经"],
            kungfu_dps_list=["冰心诀"], kungfu_pinyin_to_chinese={"bingxin": "冰心诀"},
            tuilan_request=MagicMock(side_effect=AssertionError("no foreground kungfu request")),
            defget_get=AsyncMock(side_effect=AssertionError("no foreground fallback")),
            identity_repo=self.identities, kungfu_refresh_repo=self.queue, kungfu_policy=self.policy,
            kungfu_query_service=self.direct)
        patches = [
            patch("src.services.jx3.jjc_ranking.time.time", return_value=NOW),
            patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED", 1, create=True),
            patch("src.services.jx3.jjc_ranking.cfg.JJC_KUNGFU_REFRESH_ENABLED", 1, create=True),
            patch("src.services.jx3.jjc_ranking.logger", MagicMock()),
            patch("src.services.jx3.jjc_ranking.get_db", side_effect=AssertionError("use injected repo")),
            patch("src.services.jx3.jjc_ranking.random_sleep", new=AsyncMock(side_effect=AssertionError("no per-role sleep"))),
            patch.object(JjcRankingService, "_enqueue_ranking_member_for_sync", new=AsyncMock(return_value=True)),
            patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value={"found": False})),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def resolve(self, docs):
        self.identities.resolve_ranking_identities_batch.return_value = docs
        ranking = {"data": [player(i) for i in range(len(docs))], "cache_time": NOW}
        return await self.service.resolve_ranking_kungfus(ranking)

    async def stats(self, docs, **extra):
        self.identities.resolve_ranking_identities_batch.return_value = docs
        ranking = dict({"data": [player(i) for i in range(len(docs))], "cache_time": NOW}, **extra)
        return await self.service.get_ranking_kungfu_data(ranking)

    async def test_missing_roles_are_queried_in_rank_order_and_counted_in_current_statistics(self):
        docs = [identity(0), identity(1, include_result=False), identity(2, age=301)]
        self.direct.query_now.side_effect = [identity(1)["jjc_kungfu"], identity(2)["jjc_kungfu"]]
        actual = await self.stats(docs)
        self.assertNotIn("error", actual)
        self.assertEqual([call.args[0]["_id"] for call in self.direct.query_now.await_args_list],
                         [docs[1]["_id"], docs[2]["_id"]])
        self.assertEqual(actual["kungfu_statistics"]["top_50"]["kungfu_cache"],
                         {"total": 3, "fresh": 3, "stale": 0, "unknown": 0, "coverage": 1.0})
        self.assertEqual(actual["missing_kungfu_lines"], [])
        self.assertEqual([d["_id"] for d in self.queue.register.call_args.args[0]], [docs[0]["_id"]])

    async def test_direct_query_does_not_depend_on_background_consumer_flag(self):
        self.direct.query_now.return_value = identity(0)["jjc_kungfu"]
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_KUNGFU_REFRESH_ENABLED", 0):
            actual = await self.stats([identity(0, include_result=False)])
        self.direct.query_now.assert_awaited_once()
        self.assertEqual(actual["kungfu_statistics"]["top_50"]["kungfu_cache"]["unknown"], 0)

    async def test_unresolved_identity_uses_direct_legacy_query_without_publishing_to_conflicting_role(self):
        with patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value={
                "found": True, "kungfu": "冰心诀", "kungfu_id": 10081})) as direct:
            actual = await self.stats([None])
        direct.assert_awaited_once()
        self.assertFalse(direct.call_args.kwargs["prefer_cache"])
        self.direct.query_now.assert_not_awaited()
        self.assertEqual(actual["kungfu_statistics"]["top_50"]["kungfu_cache"]["unknown"], 0)

    async def test_direct_failure_keeps_unknown_and_does_not_abort_later_roles(self):
        docs = [identity(i, include_result=False) for i in range(2)]
        self.direct.query_now.side_effect = [RuntimeError("query unavailable"), identity(1)["jjc_kungfu"]]
        actual = await self.stats(docs)
        self.assertNotIn("error", actual)
        self.assertEqual(self.direct.query_now.await_count, 2)
        self.assertEqual(actual["kungfu_statistics"]["top_50"]["kungfu_cache"]["unknown"], 1)

    async def test_failed_upstream_cached_match_fallback_is_not_falsely_fresh(self):
        old = {"found": True, "kungfu": "冰心诀", "kungfu_id": 10081,
               "kungfu_selected_source": "cached_match_detail_win_history",
               "cached_match_detail_latest_win_time": NOW - 86400}
        with patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value=old)):
            actual = await self.stats([None])
        cache = actual["kungfu_statistics"]["top_50"]["kungfu_cache"]
        self.assertEqual(cache["fresh"], 0)
        self.assertEqual(cache["unknown"], 1)

    async def test_hot_statistics_never_call_direct_lookup(self):
        actual = await self.stats([identity(0), identity(1, age=101)])
        self.direct.query_now.assert_not_awaited()
        self.assertNotIn("error", actual)

    async def test_thousand_hot_roles_are_resolved_in_one_batch_and_registered_without_foreground_queries(self):
        docs = [identity(i) for i in range(1000)]
        actual = await self.resolve(docs)
        self.assertEqual(len(actual["members"]), 1000)
        self.assertTrue(all(member["found"] and member["kungfu"] == "冰心诀"
                            for member in actual["members"]))
        self.assertFalse(actual["refresh_degraded"])
        self.identities.resolve_ranking_identities_batch.assert_awaited_once()
        self.queue.register.assert_awaited_once()
        registered = self.queue.register.call_args.args[0]
        self.assertEqual({doc["_id"] for doc in registered}, {doc["_id"] for doc in docs})
        self.service.tuilan_request.assert_not_called()
        self.service.defget_get.assert_not_awaited()

    async def test_cold_cache_read_does_not_enqueue_misses_for_async_completion(self):
        docs = [identity(i, include_result=False) for i in range(1000)]
        actual = await self.resolve(docs)
        self.assertEqual(len(actual["members"]), 1000)
        self.assertTrue(all(not member["found"] and not member.get("kungfu")
                            for member in actual["members"]))
        self.assertEqual(self.queue.register.call_args.args[0], [])
        self.service.tuilan_request.assert_not_called()
        self.service.defget_get.assert_not_awaited()

    async def test_identity_conflicts_keep_position_and_do_not_register_someone_else(self):
        docs = [identity(0), None, identity(2, include_result=False)]
        actual = await self.resolve(docs)
        self.assertEqual(len(actual["members"]), 3)
        self.assertTrue(actual["members"][0]["found"])
        self.assertFalse(actual["members"][1]["found"])
        self.assertEqual(actual["members"][1]["name"], "role-1")
        registered = self.queue.register.call_args.args[0]
        self.assertEqual({doc["_id"] for doc in registered}, {docs[0]["_id"]})

    async def test_stale_is_usable_expired_and_other_scope_are_unknown(self):
        docs = [identity(0, age=101), identity(1, age=301), identity(2)]
        docs[2]["jjc_kungfu"]["season_id"] = "previous-season"
        actual = await self.resolve(docs)
        self.assertTrue(actual["members"][0]["found"])
        self.assertEqual(actual["members"][0]["kungfu_freshness"], "stale")
        for member in actual["members"][1:]:
            self.assertFalse(member["found"])
            self.assertEqual(member["kungfu_freshness"], "unknown")
            self.assertTrue(member["kungfu_unknown_reason"])

    async def test_registration_failure_preserves_selected_results_and_marks_degraded(self):
        self.queue.register.side_effect = RuntimeError("queue unavailable")
        actual = await self.resolve([identity(0)])
        self.assertTrue(actual["members"][0]["found"])
        self.assertEqual(actual["members"][0]["kungfu"], "冰心诀")
        self.assertTrue(actual["refresh_degraded"])

    async def test_result_read_failure_returns_statistic_error_instead_of_all_unknown_success(self):
        self.identities.resolve_ranking_identities_batch.side_effect = RuntimeError("read unavailable")
        actual = await self.service.get_ranking_kungfu_data({"data": [player(0)]})
        self.assertTrue(actual["error"])
        self.queue.register.assert_not_awaited()

    async def test_no_background_consumer_does_not_disable_using_local_results(self):
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_KUNGFU_REFRESH_ENABLED", 0):
            actual = await self.resolve([identity(0), identity(1, include_result=False)])
        self.assertTrue(actual["members"][0]["found"])
        self.assertFalse(actual["members"][1]["found"])
        self.queue.register.assert_awaited_once()
        self.service.tuilan_request.assert_not_called()

    async def test_result_is_selected_before_registration_can_change_the_source(self):
        docs = [identity(0)]
        async def change_source(*args, **kwargs):
            docs[0]["jjc_kungfu"]["name"] = "云裳心经"
            docs[0]["jjc_kungfu"]["kungfu_id"] = 10080
            docs[0]["jjc_kungfu"]["publish_version"] = 2
        self.queue.register.side_effect = change_source
        actual = await self.resolve(docs)
        self.assertEqual(actual["members"][0]["kungfu"], "冰心诀")
        self.assertEqual(actual["members"][0]["kungfu_publish_version"], 1)

    async def test_each_rank_range_counts_actual_members_and_preserves_evidence(self):
        actual = await self.stats([identity(0), identity(1, age=101),
                                   identity(2, include_result=False), None])
        self.assertNotIn("error", actual)
        self.assertEqual(actual["kungfu_cache_scope"], SCOPE)
        for range_data in actual["kungfu_statistics"].values():
            cache = range_data["kungfu_cache"]
            self.assertEqual(cache, {"total": 4, "fresh": 1, "stale": 1,
                                     "unknown": 2, "coverage": 0.5})
            known = range_data["dps"]["members"]["冰心诀"]
            self.assertEqual([member["rank"] for member in known], [1, 2])
            self.assertEqual(known[0]["kungfu_verified_at"], NOW - 1)
            self.assertEqual(known[0]["kungfu_source"], "indicator")
            self.assertEqual(known[0]["kungfu_publish_version"], 1)

    async def test_cold_stats_keep_all_original_unknown_positions_in_missing_lines(self):
        actual = await self.stats([identity(i, include_result=False) for i in range(3)])
        self.assertNotIn("error", actual)
        self.assertEqual(len(actual["missing_kungfu_lines"]), 3)
        self.assertTrue(actual["missing_kungfu_lines"][0].startswith("1."))
        self.assertTrue(actual["missing_kungfu_lines"][2].startswith("3."))
        self.assertEqual(actual["kungfu_statistics"]["top_50"]["kungfu_cache"]["unknown"], 3)

    async def test_disabled_new_mode_keeps_old_get_user_kungfu_parameter(self):
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED", 0), \
             patch("src.services.jx3.jjc_ranking.cfg.JJC_KUNGFU_REFRESH_ENABLED", 0), \
             patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value={"found": False})) as old:
            actual = await self.service.get_ranking_kungfu_data({"data": [player(0)]}, use_cached_kungfu=True)
        self.assertNotIn("error", actual)
        self.assertTrue(old.call_args.kwargs["prefer_cache"])
        self.identities.resolve_ranking_identities_batch.assert_not_awaited()
        self.queue.register.assert_not_awaited()

    async def test_historical_tag_uses_old_path_and_does_not_register_current_roles(self):
        with patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value={"found": False})) as old:
            actual = await self.service.get_ranking_kungfu_data({"data": [player(0)], "explicit_tag": True})
        self.assertNotIn("error", actual)
        old.assert_awaited_once()
        self.identities.resolve_ranking_identities_batch.assert_not_awaited()
        self.queue.register.assert_not_awaited()

    async def test_refresh_only_mode_registers_current_roles_while_using_old_statistics(self):
        self.identities.resolve_ranking_identities_batch.return_value = [identity(0)]
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED", 0), \
             patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value={"found": False})) as old:
            actual = await self.service.get_ranking_kungfu_data({"data": [player(0)]})
        self.assertNotIn("error", actual)
        old.assert_awaited_once()
        self.queue.register.assert_awaited_once()

    async def test_new_kungfu_does_not_inherit_unchecked_auxiliary_as_checked(self):
        actual = await self.resolve([identity(0)])
        member = actual["members"][0]
        self.assertEqual(member["kungfu_id"], 10081)
        self.assertFalse(member.get("weapon_checked"))
        self.assertFalse(member.get("teammates_checked"))

    def test_snapshot_summary_and_details_preserve_cache_evidence(self):
        member = {"rank": 1, "name": "role-0", "kungfu_verified_at": NOW-1,
                  "kungfu_source": "indicator", "kungfu_freshness": "fresh",
                  "kungfu_publish_version": 7, "weapon_checked": False}
        stats = {"top_50": {"total_players": 1,
                 "kungfu_cache": {"total": 1, "fresh": 1, "stale": 0, "unknown": 0, "coverage": 1.0},
                 "healer": {"members": {}}, "dps": {"members": {"冰心诀": [member]}}}}
        with patch.object(JjcRankingService, "_save_ranking_stats_to_mongo", return_value=None) as save:
            self.service.save_ranking_stats({"cache_time": NOW}, stats, "第1周", payload={
                "kungfu_cache_scope": copy.deepcopy(SCOPE), "refresh_degraded": False})
        summary = save.call_args.kwargs["summary_payload"]
        details = save.call_args.kwargs["detail_payloads"]
        self.assertEqual(summary["kungfu_cache_scope"], SCOPE)
        self.assertEqual(summary["kungfu_statistics"]["top_50"]["kungfu_cache"]["coverage"], 1.0)
        self.assertEqual(next(item for item in details if item["kungfu"] == "冰心诀")["members"][0], member)


    async def test_cached_name_with_wrong_canonical_id_is_unknown(self):
        doc = identity(0)
        doc["jjc_kungfu"]["kungfu_id"] = 10080
        actual = await self.resolve([doc])
        self.assertFalse(actual["members"][0]["found"])
        self.assertEqual(actual["members"][0]["kungfu_unknown_reason"], "unknown_kungfu")

    async def test_identity_batch_losing_positions_is_an_error(self):
        self.identities.resolve_ranking_identities_batch.return_value = []
        actual = await self.service.get_ranking_kungfu_data({"data": [player(0)]})
        self.assertTrue(actual["error"])
        self.service.tuilan_request.assert_not_called()

    async def test_scope_is_frozen_before_registration_await(self):
        async def change_scope(*args, **kwargs):
            self.policy.scope["season_id"] = "season-b"
        self.queue.register.side_effect = change_scope
        actual = await self.resolve([identity(0)])
        self.assertEqual(actual["kungfu_cache_scope"], SCOPE)

    async def test_unknown_detail_keeps_rank_identity_and_reason_in_snapshot(self):
        actual = await self.stats([identity(0), identity(1, include_result=False)])
        stats = actual["kungfu_statistics"]
        self.assertTrue(stats["top_50"]["dps"]["equipment_incomplete"])
        self.assertTrue(stats["top_50"]["healer"]["equipment_incomplete"])
        details = self.service._build_detail_payloads(stats)
        unknown = next(row for row in details if row["range"] == "top_50" and row["lane"] == "unknown")
        self.assertEqual(unknown["members"][0]["rank"], 2)
        self.assertEqual(unknown["members"][0]["game_role_id"], "id-1")
        self.assertEqual(unknown["members"][0]["score"], 2199)
        self.assertEqual(unknown["members"][0]["kungfu_unknown_reason"], "missing")
        summary = self.service._build_summary_payload({"kungfu_statistics": stats})
        self.assertNotIn("unknown_members", summary["kungfu_statistics"]["top_50"])

    async def test_repository_persists_scope_degraded_and_range_coverage(self):
        collection = SimpleNamespace(update_one=AsyncMock())
        repo = JjcRankingStatsRepo(db=SimpleNamespace(jjc_ranking_stat_summaries=collection),
                                   suppress_errors=False)
        payload = {"kungfu_cache_scope": SCOPE, "refresh_degraded": True,
                   "kungfu_statistics": {"top_50": {"kungfu_cache": {"coverage": 0.5}}}}
        await repo.upsert_summary(123, payload)
        stored = collection.update_one.call_args.args[1]["$set"]
        self.assertEqual(stored["kungfu_cache_scope"], SCOPE)
        self.assertTrue(stored["refresh_degraded"])
        self.assertEqual(stored["kungfu_statistics"]["top_50"]["kungfu_cache"]["coverage"], 0.5)


    async def test_lazy_singleton_policy_factory_is_resolved_once_per_statistic(self):
        factory = MagicMock(return_value=self.policy)
        self.service = replace(self.service, kungfu_policy=factory)
        actual = await self.stats([identity(0)])
        self.assertNotIn("error", actual)
        self.assertEqual(actual["kungfu_cache_scope"], SCOPE)
        factory.assert_called_once_with()

    async def test_invalid_lazy_policy_disables_new_paths_and_retains_old_statistic(self):
        factory = MagicMock(side_effect=ValueError("invalid configured intervals"))
        self.service = replace(self.service, kungfu_policy=factory)
        with patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value={"found": False})) as old:
            actual = await self.service.get_ranking_kungfu_data({"data": [player(0)]}, use_cached_kungfu=True)
        self.assertNotIn("error", actual)
        self.assertTrue(old.call_args.kwargs["prefer_cache"])
        self.identities.resolve_ranking_identities_batch.assert_not_awaited()
        self.queue.register.assert_not_awaited()


    async def test_raw_ranking_person_info_resolves_through_real_identity_repository(self):
        doc = identity(0)
        cursor = SimpleNamespace(to_list=AsyncMock(return_value=[doc]))
        collection = SimpleNamespace(find=MagicMock(return_value=cursor))
        real_repo = RoleIdentityRepo(db=SimpleNamespace(role_identities=collection))
        self.service = replace(self.service, identity_repo=real_repo)
        ranking_player = player(0)
        ranking_player["personInfo"]["roleName"] += "·server-a"
        with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new=AsyncMock(side_effect=AssertionError("existing role must match"))):
            actual = await self.service.resolve_ranking_kungfus({"data": [ranking_player]})
        self.assertTrue(actual["members"][0]["found"])
        self.assertEqual(actual["members"][0]["name"], "role-0")
        collection.find.assert_called_once()
        self.assertEqual(self.queue.register.call_args.args[0][0]["_id"], doc["_id"])

    async def test_background_only_default_cache_hit_registers_without_cache_mutation(self):
        cached = {"code": 0, "data": [player(0)], "cache_time": NOW}
        cache = SimpleNamespace(load_ranking_cache=AsyncMock(return_value=cached))
        self.identities.resolve_ranking_identities_batch.return_value = [identity(0, include_result=False)]
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED", 0), \
             patch.object(JjcRankingService, "_cache", return_value=cache):
            actual = await self.service.query_jjc_ranking()
        self.queue.register.assert_awaited_once()
        self.assertFalse(actual["refresh_degraded"])
        self.assertNotIn("refresh_degraded", cached)
        self.service.tuilan_request.assert_not_called()

    async def test_background_only_new_default_ranking_registers_after_cache_save(self):
        response = {"code": 0, "data": [player(0)]}
        cache = SimpleNamespace(load_ranking_cache=AsyncMock(return_value=None), save_ranking_cache=AsyncMock())
        api = SimpleNamespace(get_arena_time_tag=MagicMock(return_value={"code": 0, "data": {"defaultWeek": 4}}),
                              get_arena_ranking=MagicMock(return_value=response))
        self.identities.resolve_ranking_identities_batch.return_value = [identity(0, include_result=False)]
        async def in_process(call, *args):
            return call(*args)
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED", 0), \
             patch.object(JjcRankingService, "_cache", return_value=cache), \
             patch.object(JjcRankingService, "_api", return_value=api), \
             patch("src.services.jx3.jjc_ranking.fixed_sleep", new=AsyncMock()), \
             patch("src.services.jx3.jjc_ranking.asyncio.to_thread", new=in_process):
            actual = await self.service.query_jjc_ranking()
        self.queue.register.assert_awaited_once()
        cache.save_ranking_cache.assert_awaited_once()
        self.assertFalse(actual["refresh_degraded"])
        self.assertNotIn("refresh_degraded", cache.save_ranking_cache.call_args.args[0])

    async def test_prewarm_failure_preserves_successful_board_and_propagates_to_stats(self):
        cached = {"code": 0, "data": [player(0)], "cache_time": NOW}
        cache = SimpleNamespace(load_ranking_cache=AsyncMock(return_value=cached))
        self.identities.resolve_ranking_identities_batch.side_effect = RuntimeError("read unavailable")
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_RANKING_KUNGFU_CACHE_ENABLED", 0), \
             patch.object(JjcRankingService, "_cache", return_value=cache), \
             patch.object(JjcRankingService, "get_user_kungfu", new=AsyncMock(return_value={"found": False})):
            board = await self.service.query_jjc_ranking()
            self.assertFalse(board.get("error"))
            self.assertTrue(board["refresh_degraded"])
            result = await self.service.get_ranking_kungfu_data(board)
        self.assertTrue(result["refresh_degraded"])

    async def test_disabled_refresh_query_does_not_resolve_or_register(self):
        cached = {"code": 0, "data": [player(0)]}
        cache = SimpleNamespace(load_ranking_cache=AsyncMock(return_value=cached))
        with patch("src.services.jx3.jjc_ranking.cfg.JJC_KUNGFU_REFRESH_ENABLED", 0), \
             patch.object(JjcRankingService, "_cache", return_value=cache):
            actual = await self.service.query_jjc_ranking()
        self.assertEqual(actual, cached)
        self.identities.resolve_ranking_identities_batch.assert_not_awaited()
        self.queue.register.assert_not_awaited()


    async def test_explicit_historical_query_does_not_prewarm_when_refresh_is_enabled(self):
        api = SimpleNamespace(get_arena_ranking=MagicMock(return_value={"code": 0, "data": [player(0)]}))
        async def in_process(call, *args):
            return call(*args)
        with patch.object(JjcRankingService, "_api", return_value=api), \
             patch("src.services.jx3.jjc_ranking.asyncio.to_thread", new=in_process):
            result = await self.service.query_jjc_ranking(tag=4)
        self.assertTrue(result["explicit_tag"])
        self.assertNotIn("refresh_degraded", result)
        self.identities.resolve_ranking_identities_batch.assert_not_awaited()
        self.queue.register.assert_not_awaited()

    def test_empty_unknown_details_are_emitted_in_new_and_rollback_modes(self):
        for extra in ({"unknown_members": []}, {}):
            stats = {"top_50": {"healer": {"members": {}}, "dps": {"members": {}}, **extra}}
            details = self.service._build_detail_payloads(stats)
            unknown = [d for d in details if d["lane"] == "unknown"]
            self.assertEqual(len(unknown), 1)
            self.assertEqual(unknown[0]["members"], [])
