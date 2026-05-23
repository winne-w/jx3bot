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


def _install_router_import_stubs() -> None:
    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.APIRouter = _FakeRouter
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
    singletons_mod.jjc_ranking_inspect_service = object()
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


if __name__ == "__main__":
    unittest.main()
