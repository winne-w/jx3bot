from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional


class _FakeRouter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.routes: List[Any] = []

    def get(self, *args: Any, **kwargs: Any) -> Any:
        def decorator(func: Any) -> Any:
            self.routes.append(func)
            return func

        return decorator

    def post(self, *args: Any, **kwargs: Any) -> Any:
        def decorator(func: Any) -> Any:
            self.routes.append(func)
            return func

        return decorator


class _FakeRepo:
    def __init__(
        self,
        list_result: Any = None,
        summary: Optional[Dict[str, Any]] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.list_result = list_result
        self.summary = summary
        self.detail = detail
        self.list_calls: List[Dict[str, Any]] = []
        self.summary_calls: List[int] = []
        self.detail_calls: List[Dict[str, Any]] = []

    async def list_timestamps(self, **kwargs: Any) -> Any:
        self.list_calls.append(kwargs)
        return self.list_result

    async def load_summary(self, timestamp: int) -> Optional[Dict[str, Any]]:
        self.summary_calls.append(timestamp)
        return self.summary

    async def load_detail(
        self,
        timestamp: int,
        range_key: str,
        lane: str,
        kungfu: str,
    ) -> Optional[Dict[str, Any]]:
        self.detail_calls.append({
            "timestamp": timestamp,
            "range_key": range_key,
            "lane": lane,
            "kungfu": kungfu,
        })
        return self.detail


class _FakePeakRepo:
    def __init__(self, doc: Dict[str, Any]) -> None:
        self.doc = doc
        self.calls: List[Dict[str, Any]] = []

    async def load_result(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return self.doc


class _FakeInspectService:
    def __init__(self) -> None:
        self.synced_role_result: Dict[str, Any] = {}
        self.synced_matches_result: Dict[str, Any] = {}
        self.enqueue_result: Dict[str, Any] = {}
        self.role_indicator_result: Dict[str, Any] = {}
        self.synced_role_calls: List[Dict[str, Any]] = []
        self.synced_matches_calls: List[Dict[str, Any]] = []
        self.enqueue_calls: List[Dict[str, Any]] = []
        self.role_indicator_calls: List[Dict[str, Any]] = []

    async def resolve_synced_role(self, **kwargs: Any) -> Dict[str, Any]:
        self.synced_role_calls.append(kwargs)
        return self.synced_role_result

    async def get_synced_role_matches(self, **kwargs: Any) -> Dict[str, Any]:
        self.synced_matches_calls.append(kwargs)
        return self.synced_matches_result

    async def enqueue_synced_role(self, **kwargs: Any) -> Dict[str, Any]:
        self.enqueue_calls.append(kwargs)
        return self.enqueue_result

    async def get_role_indicator(self, **kwargs: Any) -> Dict[str, Any]:
        self.role_indicator_calls.append(kwargs)
        return self.role_indicator_result


def _install_router_import_stubs() -> None:
    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.APIRouter = _FakeRouter
    fastapi_mod.Body = lambda default=None, **kwargs: default
    fastapi_mod.Query = lambda default=..., **kwargs: default
    sys.modules["fastapi"] = fastapi_mod

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None)
    sys.modules["nonebot"] = nonebot_mod

    api_response_mod = types.ModuleType("src.api.response")
    api_response_mod.success_response = lambda data: {
        "status_code": 0,
        "status_msg": "success",
        "data": data,
    }
    api_response_mod.error_response = lambda message, **kwargs: {
        "status_code": kwargs.get("status_code", 1),
        "status_msg": message,
        "data": kwargs.get("data") or {},
    }
    sys.modules["src.api.response"] = api_response_mod

    singletons_mod = types.ModuleType("src.services.jx3.singletons")
    singletons_mod.jjc_ranking_inspect_service = _FakeInspectService()
    sys.modules["src.services.jx3.singletons"] = singletons_mod

    repo_mod = types.ModuleType("src.storage.mongo_repos.jjc_ranking_stats_repo")
    repo_mod.JjcRankingStatsRepo = object
    sys.modules["src.storage.mongo_repos.jjc_ranking_stats_repo"] = repo_mod


def _load_router_module() -> Any:
    _install_router_import_stubs()
    module_path = Path(__file__).resolve().parents[1] / "src" / "api" / "routers" / "jjc_ranking_stats.py"
    spec = importlib.util.spec_from_file_location("jjc_ranking_stats_router_under_test", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load jjc_ranking_stats router module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRankingStatsListRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_unpaged_list_returns_mongo_timestamps_only(self) -> None:
        module = _load_router_module()
        repo = _FakeRepo(list_result=[300, 100])
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats(action="list")

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["data"], [300, 100])
        self.assertEqual(repo.list_calls, [{}])

    async def test_with_meta_true_passes_to_repo_with_default_pagination(self) -> None:
        module = _load_router_module()
        repo = _FakeRepo(list_result={
            "items": [
                {
                    "timestamp": 300,
                    "generated_at": 1000.0,
                    "ranking_cache_time": 1000.5,
                    "default_week": 3,
                    "current_season": "S3",
                    "week_info": "第3周",
                    "is_settlement": False,
                    "snapshot_kind": "daily",
                },
            ],
            "page": 1,
            "page_size": 100,
            "total": 1,
            "has_more": False,
        })
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats(action="list", with_meta=True)

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(repo.list_calls, [{"page": 1, "page_size": 100, "with_meta": True}])

    async def test_with_meta_true_respects_custom_pagination(self) -> None:
        module = _load_router_module()
        repo = _FakeRepo(list_result={
            "items": [],
            "page": 2,
            "page_size": 5,
            "total": 0,
            "has_more": False,
        })
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats(action="list", with_meta=True, page=2, page_size=5)

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(repo.list_calls, [{"page": 2, "page_size": 5, "with_meta": True}])

    async def test_with_meta_false_paged_does_not_pass_with_meta(self) -> None:
        module = _load_router_module()
        repo = _FakeRepo(list_result={
            "items": [300],
            "page": 1,
            "page_size": 20,
            "total": 1,
            "has_more": False,
        })
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats(action="list", page=1)

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(repo.list_calls, [{"page": 1, "page_size": 20}])

    async def test_paged_list_returns_mongo_page_even_when_empty(self) -> None:
        module = _load_router_module()
        repo = _FakeRepo(list_result={
            "items": [],
            "page": 2,
            "page_size": 2,
            "total": 0,
            "has_more": False,
        })
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats(action="list", page=2, page_size=2)

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["data"], {
            "items": [],
            "page": 2,
            "page_size": 2,
            "total": 0,
            "has_more": False,
        })
        self.assertEqual(repo.list_calls, [{"page": 2, "page_size": 2}])


class TestRankingStatsMongoHitRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_read_returns_mongo_summary_without_file_lookup(self) -> None:
        module = _load_router_module()
        mongo_summary = {"timestamp": 123, "kungfu_statistics": {"top_200": {}}}
        repo = _FakeRepo(summary=mongo_summary)
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats(action="read", timestamp="123")

        self.assertEqual(response["status_code"], 0)
        self.assertIs(response["data"], mongo_summary)
        self.assertEqual(repo.summary_calls, [123])

    async def test_read_returns_not_found_when_mongo_misses(self) -> None:
        module = _load_router_module()
        repo = _FakeRepo(summary=None)
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats(action="read", timestamp="123")

        self.assertEqual(response["status_code"], 1)
        self.assertEqual(response["status_msg"], "not_found")
        self.assertEqual(repo.summary_calls, [123])

    async def test_details_returns_mongo_detail_with_normalized_lane_and_params(self) -> None:
        module = _load_router_module()
        mongo_detail = {
            "timestamp": 123,
            "range": "top_200",
            "lane": "dps",
            "kungfu": "花间游",
            "members": [{"name": "A"}],
        }
        repo = _FakeRepo(detail=mongo_detail)
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats_details(
            timestamp="123",
            range_key=" top_200 ",
            lane=" DPS ",
            kungfu=" 花间游 ",
        )

        self.assertEqual(response["status_code"], 0)
        self.assertIs(response["data"], mongo_detail)
        self.assertEqual(repo.detail_calls, [{
            "timestamp": 123,
            "range_key": "top_200",
            "lane": "dps",
            "kungfu": "花间游",
        }])

    async def test_details_returns_not_found_when_mongo_misses(self) -> None:
        module = _load_router_module()
        repo = _FakeRepo(detail=None)
        module.JjcRankingStatsRepo = lambda: repo

        response = await module.get_ranking_stats_details(
            timestamp="123",
            range_key="top_200",
            lane="dps",
            kungfu="花间游",
        )

        self.assertEqual(response["status_code"], 1)
        self.assertEqual(response["status_msg"], "not_found")
        self.assertEqual(repo.detail_calls, [{
            "timestamp": 123,
            "range_key": "top_200",
            "lane": "dps",
            "kungfu": "花间游",
        }])


class TestPeakScoreRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_peak_score_distribution_can_skip_match_summary(self) -> None:
        module = _load_router_module()
        peak_repo = _FakePeakRepo({
            "anchor_timestamp": 123,
            "window_start": 123 - 14 * 86400,
            "window_end": 123,
            "score_type": "game",
            "version": 1,
            "status": "done",
            "item_count": 1,
            "items": [{
                "rank": 1,
                "score": 2600,
                "match_id": 5001,
                "kungfu": "花间游",
                "role_name": "角色A",
                "server": "梦江南",
            }],
        })
        module.JjcPeakScoreRankingRepo = lambda: peak_repo

        response = await module.get_jjc_peak_score_ranking(
            timestamp="123",
            score_type="game",
            range_key="top_1000",
            include_match_summary=False,
        )

        self.assertEqual(response["status_code"], 0)
        data = response["data"]
        self.assertEqual(data["item_count"], 1)
        self.assertNotIn("cached_detail_summary", data["items"][0])
        self.assertEqual(data["kungfu_statistics"]["dps"]["distribution"]["花间游"], 1)
        self.assertEqual(peak_repo.calls[0]["items_limit"], 1000)


class TestSyncedRoleRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_role_indicator_forwards_identity_only_flag(self) -> None:
        module = _load_router_module()
        service = _FakeInspectService()
        service.role_indicator_result = {"indicator": {"score": 2500}}
        module.jjc_ranking_inspect_service = service

        response = await module.get_ranking_stats_role_indicator(
            server=" 梦江南 ",
            name=" 角色A ",
            game_role_id=" 100 ",
            global_role_id=None,
            role_id=None,
            zone=" 电信区 ",
            identity_only=True,
        )

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(service.role_indicator_calls, [{
            "server": "梦江南",
            "name": "角色A",
            "game_role_id": "100",
            "global_role_id": None,
            "role_id": None,
            "zone": "电信区",
            "force_refresh": False,
            "identity_only": True,
        }])

    async def test_synced_role_trims_params_and_returns_standard_success(self) -> None:
        module = _load_router_module()
        service = _FakeInspectService()
        service.synced_role_result = {
            "identity": {"identity_id": "id-1"},
            "sync_status": {"status": "not_queued"},
        }
        module.jjc_ranking_inspect_service = service

        response = await module.get_ranking_stats_synced_role(server=" 梦江南 ", name=" 角色A ")

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["status_msg"], "success")
        self.assertEqual(service.synced_role_calls, [{"server": "梦江南", "name": "角色A"}])

    async def test_synced_role_allows_empty_server_for_candidates(self) -> None:
        module = _load_router_module()
        service = _FakeInspectService()
        service.synced_role_result = {
            "error": True,
            "message": "role_identity_not_found",
            "candidates": [],
        }
        module.jjc_ranking_inspect_service = service

        response = await module.get_ranking_stats_synced_role(server=" ", name=" 角色A ")

        self.assertEqual(response["status_code"], 1)
        self.assertEqual(response["status_msg"], "role_identity_not_found")
        self.assertEqual(service.synced_role_calls, [{"server": "", "name": "角色A"}])

    async def test_synced_role_missing_returns_role_identity_not_found(self) -> None:
        module = _load_router_module()
        service = _FakeInspectService()
        service.synced_role_result = {"error": True, "message": "role_identity_not_found"}
        module.jjc_ranking_inspect_service = service

        response = await module.get_ranking_stats_synced_role(server="梦江南", name="不存在")

        self.assertEqual(response["status_code"], 1)
        self.assertEqual(response["status_msg"], "role_identity_not_found")

    async def test_synced_role_matches_uses_page_params(self) -> None:
        module = _load_router_module()
        service = _FakeInspectService()
        service.synced_matches_result = {
            "pagination": {"page": 2, "page_size": 5, "total": 0, "has_more": False},
            "recent_matches": [],
        }
        module.jjc_ranking_inspect_service = service

        response = await module.get_ranking_stats_synced_role_matches(
            server="梦江南",
            name="角色A",
            page=2,
            page_size=5,
        )

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(service.synced_matches_calls, [{
            "server": "梦江南",
            "name": "角色A",
            "page": 2,
            "page_size": 5,
        }])

    async def test_synced_role_sync_accepts_json_payload_and_returns_standard_shape(self) -> None:
        module = _load_router_module()
        service = _FakeInspectService()
        service.enqueue_result = {
            "queued": True,
            "sync_status": {"status": "queued", "priority": 2},
        }
        module.jjc_ranking_inspect_service = service

        response = await module.post_ranking_stats_synced_role_sync(
            payload={"server": " 梦江南 ", "name": " 角色A "},
        )

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["data"]["queued"], True)
        self.assertEqual(service.enqueue_calls, [{"server": "梦江南", "name": "角色A"}])

    async def test_synced_role_sync_accepts_query_fallback(self) -> None:
        module = _load_router_module()
        service = _FakeInspectService()
        service.enqueue_result = {
            "queued": True,
            "sync_status": {"status": "queued", "priority": 2},
        }
        module.jjc_ranking_inspect_service = service

        response = await module.post_ranking_stats_synced_role_sync(
            server=" 梦江南 ",
            name=" 角色A ",
        )

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(service.enqueue_calls, [{"server": "梦江南", "name": "角色A"}])


if __name__ == "__main__":
    unittest.main()
