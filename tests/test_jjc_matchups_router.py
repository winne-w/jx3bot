from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional


class _FakeRouter:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.prefix = kwargs.get("prefix", "")
        self.routes: List[Dict[str, Any]] = []

    def get(self, path: str, *args: Any, **kwargs: Any) -> Any:
        return self._decorate("GET", path)

    def post(self, path: str, *args: Any, **kwargs: Any) -> Any:
        return self._decorate("POST", path)

    def _decorate(self, method: str, path: str) -> Any:
        def decorator(func: Any) -> Any:
            self.routes.append({"method": method, "path": path, "handler": func})
            return func

        return decorator


class _FakeRequest:
    def __init__(self, payload: Any = None, json_error: Optional[Exception] = None) -> None:
        self.payload = payload
        self.json_error = json_error
        self.json_calls = 0

    async def json(self) -> Any:
        self.json_calls += 1
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class _FakeMatchupService:
    def __init__(self) -> None:
        self.meta_result: Dict[str, Any] = {"kungfus": [{"id": 10080}]}
        self.search_result: Dict[str, Any] = {"items": [{"match_id": 42}]}
        self.meta_error: Optional[Exception] = None
        self.search_error: Optional[Exception] = None
        self.meta_calls = 0
        self.search_calls: List[Dict[str, Any]] = []

    def get_meta(self) -> Dict[str, Any]:
        self.meta_calls += 1
        if self.meta_error is not None:
            raise self.meta_error
        return self.meta_result

    async def search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.search_calls.append(payload)
        if self.search_error is not None:
            raise self.search_error
        return self.search_result


class _ResponseSpy:
    def __init__(self) -> None:
        self.success_calls: List[Any] = []
        self.error_calls: List[Dict[str, Any]] = []

    def success_response(self, data: Any) -> Dict[str, Any]:
        self.success_calls.append(data)
        return {"status_code": 0, "status_msg": "success", "data": data}

    def error_response(
        self,
        message: str,
        *,
        data: Optional[Any] = None,
        status_code: int = 1,
    ) -> Dict[str, Any]:
        self.error_calls.append({
            "message": message,
            "data": data,
            "status_code": status_code,
        })
        return {
            "status_code": status_code,
            "status_msg": message,
            "data": data or {},
        }


def _install_router_import_stubs() -> Dict[str, Any]:
    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.APIRouter = _FakeRouter
    fastapi_mod.Request = object
    sys.modules["fastapi"] = fastapi_mod

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.logger = types.SimpleNamespace(
        error=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    sys.modules["nonebot"] = nonebot_mod

    response_spy = _ResponseSpy()
    api_response_mod = types.ModuleType("src.api.response")
    api_response_mod.success_response = response_spy.success_response
    api_response_mod.error_response = response_spy.error_response
    sys.modules["src.api.response"] = api_response_mod

    matchup_service = _FakeMatchupService()
    singletons_mod = types.ModuleType("src.services.jx3.singletons")
    singletons_mod.jjc_matchup_service = matchup_service
    sys.modules["src.services.jx3.singletons"] = singletons_mod
    return {
        "response_spy": response_spy,
        "matchup_service": matchup_service,
    }


def _load_router_module() -> Any:
    stubbed_modules = (
        "fastapi",
        "nonebot",
        "src.api.response",
        "src.services.jx3.singletons",
    )
    originals = {name: sys.modules.get(name) for name in stubbed_modules}
    stubs = _install_router_import_stubs()
    try:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "api"
            / "routers"
            / "jjc_matchups.py"
        )
        spec = importlib.util.spec_from_file_location(
            "jjc_matchups_router_under_test",
            str(module_path),
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("failed to load jjc_matchups router module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    module._response_spy = stubs["response_spy"]
    module._stubbed_matchup_service = stubs["matchup_service"]
    return module


def _get_route_handler(module: Any, method: str, path: str) -> Any:
    for route in module.router.routes:
        if route["method"] == method and route["path"] == path:
            return route["handler"]
    raise AssertionError("missing {} {} route".format(method, path))


class _FakeApiApp:
    def __init__(self) -> None:
        self.included_routers: List[Any] = []
        self.mounted_paths: List[str] = []

    def include_router(self, router: Any) -> None:
        self.included_routers.append(router)

    def mount(self, path: str, *args: Any, **kwargs: Any) -> None:
        self.mounted_paths.append(path)


def _router_with_routes(prefix: str, routes: List[str]) -> Any:
    router = _FakeRouter(prefix=prefix)
    for path in routes:
        router.routes.append({"method": "GET", "path": path, "handler": object()})
    return router


def _load_api_init_module() -> Any:
    module_names = (
        "fastapi",
        "fastapi.staticfiles",
        "src.api.routers",
    )
    originals = {name: sys.modules.get(name) for name in module_names}

    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.FastAPI = _FakeApiApp
    staticfiles_mod = types.ModuleType("fastapi.staticfiles")
    staticfiles_mod.StaticFiles = lambda **kwargs: kwargs
    routers_mod = types.ModuleType("src.api.routers")
    router_modules: Dict[str, Any] = {}
    for name in (
        "announcements",
        "arena",
        "jjc_ranking_stats",
        "jjc_sync",
        "mongo_health",
        "servers",
    ):
        module = types.ModuleType("src.api.routers." + name)
        module.router = _router_with_routes("/api/" + name, [])
        setattr(routers_mod, name, module)
        router_modules[name] = module

    matchup_module = types.ModuleType("src.api.routers.jjc_matchups")
    matchup_module.router = _router_with_routes(
        "/api/jjc",
        ["/matchups/meta", "/matchups/search"],
    )
    setattr(routers_mod, "jjc_matchups", matchup_module)
    router_modules["jjc_matchups"] = matchup_module

    sys.modules["fastapi"] = fastapi_mod
    sys.modules["fastapi.staticfiles"] = staticfiles_mod
    sys.modules["src.api.routers"] = routers_mod
    try:
        module_path = Path(__file__).resolve().parents[1] / "src" / "api" / "__init__.py"
        spec = importlib.util.spec_from_file_location("api_init_under_test", str(module_path))
        if spec is None or spec.loader is None:
            raise RuntimeError("failed to load API initializer module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    module._router_modules = router_modules
    return module


def _new_recording_constructor() -> Any:
    class RecordingConstructor:
        instances: List[Any] = []
        calls: List[Dict[str, Any]] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            type(self).instances.append(self)
            type(self).calls.append({"args": args, "kwargs": kwargs})

    return RecordingConstructor


class _NoopConstructor:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


def _stub_module(name: str, **exports: Any) -> Any:
    module = types.ModuleType(name)
    for export_name, value in exports.items():
        setattr(module, export_name, value)
    return module


def _load_singletons_module_with_constructor_spies() -> Any:
    fact_repo_constructor = _new_recording_constructor()
    matchup_service_constructor = _new_recording_constructor()
    fact_projector_constructor = _new_recording_constructor()
    config_mod = _stub_module(
        "config",
        KUNGFU_META={"demo": {"name": "示例心法", "category": "dps"}},
        CURRENT_SEASON="test-season",
        CURRENT_SEASON_START="0",
        TOKEN="",
        TICKET="",
        API_URLS={
            "竞技查询": "",
            "竞技场时间查询": "",
            "竞技场排行榜查询": "",
            "竞技场战局详情": "",
            "竞技场战局回放": "",
            "竞技场战局历史": "",
            "竞技场个人战局历史": "",
            "推栏角色指标": "",
        },
    )
    module_stubs = {
        "config": config_mod,
        "jinja2": _stub_module(
            "jinja2",
            Environment=_NoopConstructor,
            FileSystemLoader=_NoopConstructor,
        ),
        "src.infra.jx3api_get": _stub_module("src.infra.jx3api_get", get=lambda *args, **kwargs: None),
        "src.storage.mongo_repos.group_config_repo": _stub_module(
            "src.storage.mongo_repos.group_config_repo", GroupConfigRepo=_NoopConstructor
        ),
        "src.services.jx3.jjc_ranking_inspect": _stub_module(
            "src.services.jx3.jjc_ranking_inspect", JjcRankingInspectService=_NoopConstructor
        ),
        "src.services.jx3.jjc_ranking": _stub_module(
            "src.services.jx3.jjc_ranking", JjcRankingService=_NoopConstructor
        ),
        "src.services.jx3.jjc_matchup": _stub_module(
            "src.services.jx3.jjc_matchup", JjcMatchupService=matchup_service_constructor
        ),
        "src.services.jx3.jjc_match_data_sync": _stub_module(
            "src.services.jx3.jjc_match_data_sync",
            JjcMatchDataSyncService=_NoopConstructor,
            parse_season_start_timestamp=lambda value: 0,
        ),
        "src.storage.mongo_repos.jjc_sync_repo": _stub_module(
            "src.storage.mongo_repos.jjc_sync_repo", JjcSyncRepo=_NoopConstructor
        ),
        "src.services.jx3.jjc_cache_repo": _stub_module(
            "src.services.jx3.jjc_cache_repo", JjcCacheRepo=_NoopConstructor
        ),
        "src.services.jx3.kungfu": _stub_module(
            "src.services.jx3.kungfu", get_role_indicator=lambda *args, **kwargs: None
        ),
        "src.services.jx3.match_history": _stub_module(
            "src.services.jx3.match_history",
            MatchHistoryClient=_NoopConstructor,
            PersonMatchHistoryClient=_NoopConstructor,
        ),
        "src.services.jx3.match_detail": _stub_module(
            "src.services.jx3.match_detail", MatchDetailClient=_NoopConstructor
        ),
        "src.services.jx3.match_detail_identity_projection": _stub_module(
            "src.services.jx3.match_detail_identity_projection",
            MatchDetailIdentityProjectionService=_NoopConstructor,
        ),
        "src.services.jx3.match_detail_fact_projection": _stub_module(
            "src.services.jx3.match_detail_fact_projection",
            MatchDetailFactProjectionService=fact_projector_constructor,
        ),
        "src.services.jx3.match_replay": _stub_module(
            "src.services.jx3.match_replay", MatchReplayClient=_NoopConstructor
        ),
        "src.services.jx3.role_indicator": _stub_module(
            "src.services.jx3.role_indicator", RoleIndicatorClient=_NoopConstructor
        ),
        "src.storage.mongo_repos.jjc_inspect_repo": _stub_module(
            "src.storage.mongo_repos.jjc_inspect_repo", JjcInspectRepo=_NoopConstructor
        ),
        "src.storage.mongo_repos.jjc_match_participant_repo": _stub_module(
            "src.storage.mongo_repos.jjc_match_participant_repo",
            JjcMatchParticipantRepo=_NoopConstructor,
        ),
        "src.storage.mongo_repos.jjc_match_fact_repo": _stub_module(
            "src.storage.mongo_repos.jjc_match_fact_repo", JjcMatchFactRepo=fact_repo_constructor
        ),
        "src.storage.mongo_repos.jjc_match_snapshot_repo": _stub_module(
            "src.storage.mongo_repos.jjc_match_snapshot_repo", JjcMatchSnapshotRepo=_NoopConstructor
        ),
        "src.storage.mongo_repos.role_identity_repo": _stub_module(
            "src.storage.mongo_repos.role_identity_repo", RoleIdentityRepo=_NoopConstructor
        ),
        "src.services.jx3.match_detail_participant_projection": _stub_module(
            "src.services.jx3.match_detail_participant_projection",
            MatchDetailParticipantProjectionService=_NoopConstructor,
        ),
        "src.services.jx3.match_detail_persistence": _stub_module(
            "src.services.jx3.match_detail_persistence", MatchDetailPersistenceService=_NoopConstructor
        ),
        "src.utils.tuilan_request": _stub_module(
            "src.utils.tuilan_request", tuilan_request=lambda *args, **kwargs: None
        ),
    }
    originals = {name: sys.modules.get(name) for name in module_stubs}
    try:
        sys.modules.update(module_stubs)
        module_path = Path(__file__).resolve().parents[1] / "src" / "services" / "jx3" / "singletons.py"
        spec = importlib.util.spec_from_file_location("jjc_singletons_under_test", str(module_path))
        if spec is None or spec.loader is None:
            raise RuntimeError("failed to load JJC singleton module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    module._fact_repo_constructor = fact_repo_constructor
    module._matchup_service_constructor = matchup_service_constructor
    module._fact_projector_constructor = fact_projector_constructor
    return module


class TestJjcMatchupsRouter(unittest.IsolatedAsyncioTestCase):
    def _module_with_service(self) -> Any:
        module = _load_router_module()
        self.assertIs(module.jjc_matchup_service, module._stubbed_matchup_service)
        service = _FakeMatchupService()
        module.jjc_matchup_service = service
        return module

    def _assert_standard_success(self, module: Any, response: Dict[str, Any], data: Any) -> None:
        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["status_msg"], "success")
        self.assertIs(response["data"], data)
        self.assertEqual(module._response_spy.success_calls, [data])
        self.assertEqual(module._response_spy.error_calls, [])

    def _assert_standard_error(
        self, module: Any, response: Dict[str, Any], message: str
    ) -> None:
        self.assertNotEqual(response["status_code"], 0)
        self.assertEqual(response["status_msg"], message)
        self.assertEqual(response["data"], {})
        self.assertEqual(module._response_spy.success_calls, [])
        self.assertEqual(len(module._response_spy.error_calls), 1)
        self.assertEqual(module._response_spy.error_calls[0]["message"], message)

    async def test_meta_registers_exact_path_and_wraps_service_data_in_success_response(self) -> None:
        module = self._module_with_service()
        handler = _get_route_handler(module, "GET", "/matchups/meta")

        self.assertEqual(module.router.prefix + "/matchups/meta", "/api/jjc/matchups/meta")
        response = await handler()

        self._assert_standard_success(module, response, module.jjc_matchup_service.meta_result)
        self.assertEqual(module.jjc_matchup_service.meta_calls, 1)

    async def test_meta_wraps_service_exception_without_leaking_it(self) -> None:
        module = self._module_with_service()
        module.jjc_matchup_service.meta_error = RuntimeError(
            "internal-storage-connection-detail"
        )
        handler = _get_route_handler(module, "GET", "/matchups/meta")

        response = await handler()

        self._assert_standard_error(module, response, "matchup_service_unavailable")
        self.assertNotIn("internal-storage-connection-detail", response["status_msg"])
        self.assertEqual(module.jjc_matchup_service.meta_calls, 1)

    async def test_search_registers_exact_path_and_returns_service_data_unchanged(self) -> None:
        module = self._module_with_service()
        handler = _get_route_handler(module, "POST", "/matchups/search")
        payload = {
            "start_time": 1_700_000_000,
            "end_time": 1_700_086_400,
            "score_min": 0,
            "score_max": 1_000_000,
            "team_a_kungfu_ids": [10080],
            "team_b_kungfu_ids": [10242],
        }
        request = _FakeRequest(payload)

        self.assertEqual(module.router.prefix + "/matchups/search", "/api/jjc/matchups/search")
        response = await handler(request)

        self._assert_standard_success(module, response, module.jjc_matchup_service.search_result)
        self.assertEqual(request.json_calls, 1)
        self.assertEqual(module.jjc_matchup_service.search_calls, [payload])

    async def test_search_rejects_non_object_json_without_calling_service(self) -> None:
        for payload in ([], "not an object", None):
            with self.subTest(payload=payload):
                module = self._module_with_service()
                handler = _get_route_handler(module, "POST", "/matchups/search")
                request = _FakeRequest(payload)

                response = await handler(request)

                self._assert_standard_error(module, response, "invalid_request")
                self.assertEqual(request.json_calls, 1)
                self.assertEqual(module.jjc_matchup_service.search_calls, [])

    async def test_search_catches_malformed_json_inside_route_without_calling_service(self) -> None:
        errors = (
            json.JSONDecodeError("Expecting value", "{", 1),
            ValueError("request body is malformed"),
        )
        for json_error in errors:
            with self.subTest(json_error=type(json_error).__name__):
                module = self._module_with_service()
                handler = _get_route_handler(module, "POST", "/matchups/search")
                request = _FakeRequest(json_error=json_error)

                response = await handler(request)

                self._assert_standard_error(module, response, "invalid_request")
                self.assertEqual(request.json_calls, 1)
                self.assertEqual(module.jjc_matchup_service.search_calls, [])

    async def test_search_wraps_field_type_validation_error(self) -> None:
        module = self._module_with_service()
        module.jjc_matchup_service.search_error = ValueError("page must be an integer")
        handler = _get_route_handler(module, "POST", "/matchups/search")
        payload = {
            "start_time": 1_700_000_000,
            "end_time": 1_700_086_400,
            "score_min": "0",
            "score_max": 1_000_000,
        }

        response = await handler(_FakeRequest(payload))

        self._assert_standard_error(module, response, "invalid_request")
        self.assertNotIn("page must be an integer", response["status_msg"])
        self.assertEqual(module.jjc_matchup_service.search_calls, [payload])

    async def test_search_wraps_out_of_range_page_error(self) -> None:
        module = self._module_with_service()
        module.jjc_matchup_service.search_error = ValueError("page must be at most 100000")
        handler = _get_route_handler(module, "POST", "/matchups/search")
        payload = {
            "start_time": 1_700_000_000,
            "end_time": 1_700_086_400,
            "score_min": 0,
            "score_max": 1_000_000,
            "page": 100_001,
        }

        response = await handler(_FakeRequest(payload))

        self._assert_standard_error(module, response, "invalid_request")
        self.assertNotIn("page must be at most 100000", response["status_msg"])
        self.assertEqual(module.jjc_matchup_service.search_calls, [payload])

    async def test_search_wraps_service_exception_without_leaking_it(self) -> None:
        module = self._module_with_service()
        module.jjc_matchup_service.search_error = RuntimeError(
            "internal-storage-connection-detail"
        )
        handler = _get_route_handler(module, "POST", "/matchups/search")
        payload = {
            "start_time": 1_700_000_000,
            "end_time": 1_700_086_400,
            "score_min": 0,
            "score_max": 1_000_000,
        }

        response = await handler(_FakeRequest(payload))

        self._assert_standard_error(module, response, "matchup_service_unavailable")
        self.assertNotIn("internal-storage-connection-detail", response["status_msg"])
        self.assertEqual(module.jjc_matchup_service.search_calls, [payload])


class TestJjcMatchupsApiRegistration(unittest.TestCase):
    def test_register_api_includes_both_matchup_routes(self) -> None:
        module = _load_api_init_module()
        app = _FakeApiApp()

        module.register_api(app)

        matchup_router = module._router_modules["jjc_matchups"].router
        self.assertIn(matchup_router, app.included_routers)
        registered_paths = {
            router.prefix + route["path"]
            for router in app.included_routers
            for route in router.routes
        }
        self.assertTrue({
            "/api/jjc/matchups/meta",
            "/api/jjc/matchups/search",
        }.issubset(registered_paths))


class TestJjcMatchupsSingletonAssembly(unittest.TestCase):
    def test_matchup_service_and_fact_projector_share_the_fact_repo_instance(self) -> None:
        module = _load_singletons_module_with_constructor_spies()
        fact_repo_constructor = module._fact_repo_constructor
        matchup_service_constructor = module._matchup_service_constructor
        fact_projector_constructor = module._fact_projector_constructor

        self.assertEqual(len(fact_repo_constructor.instances), 1)
        fact_repo = fact_repo_constructor.instances[0]
        self.assertIs(module.jjc_match_fact_repo, fact_repo)
        self.assertEqual(matchup_service_constructor.calls, [{
            "args": (),
            "kwargs": {"matchup_repo": fact_repo, "season_start_time": 0},
        }])
        self.assertEqual(fact_projector_constructor.calls, [{
            "args": (),
            "kwargs": {"fact_repo": fact_repo},
        }])


if __name__ == "__main__":
    unittest.main()
