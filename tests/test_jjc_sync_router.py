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


class _FakeSyncService:
    def __init__(self) -> None:
        self.queue_calls: List[Dict[str, Any]] = []

    async def queue_status(self) -> Dict[str, Any]:
        return {
            "counts": {"pending": 2, "syncing": 1},
            "workers": [{"worker_id": "worker-1", "status": "idle", "online": True, "effective_status": "idle"}],
            "worker_running": True,
            "background_running": True,
        }

    async def list_queue(
        self,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        server: Optional[str] = None,
        name: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        self.queue_calls.append({
            "status": status,
            "mode": mode,
            "server": server,
            "name": name,
            "page": page,
            "page_size": page_size,
        })
        total = 100
        return {
            "items": [],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": page * page_size < total,
        }

    async def list_workers(self) -> Dict[str, Any]:
        return {"items": [{"worker_id": "worker-1", "status": "idle", "online": True, "effective_status": "idle"}]}


def _install_router_import_stubs() -> None:
    fastapi_mod = types.ModuleType("fastapi")
    fastapi_mod.APIRouter = _FakeRouter
    fastapi_mod.Query = lambda default=..., **kwargs: default
    sys.modules["fastapi"] = fastapi_mod

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.logger = types.SimpleNamespace(warning=lambda *args, **kwargs: None)
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
    singletons_mod.jjc_match_data_sync_service = _FakeSyncService()
    sys.modules["src.services.jx3.singletons"] = singletons_mod


def _load_router_module() -> Any:
    stubbed_modules = (
        "fastapi",
        "nonebot",
        "src.api.response",
        "src.services.jx3.singletons",
    )
    originals = {name: sys.modules.get(name) for name in stubbed_modules}
    _install_router_import_stubs()
    module_path = Path(__file__).resolve().parents[1] / "src" / "api" / "routers" / "jjc_sync.py"
    spec = importlib.util.spec_from_file_location("jjc_sync_router_under_test", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load jjc_sync router module")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


class TestJjcSyncRouter(unittest.IsolatedAsyncioTestCase):
    async def test_status_calls_queue_status(self) -> None:
        module = _load_router_module()

        response = await module.get_jjc_sync_status()

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["data"]["counts"], {"pending": 2, "syncing": 1})
        self.assertTrue(response["data"]["worker_running"])
        self.assertTrue(response["data"]["background_running"])

    async def test_queue_trims_empty_status_and_passes_pagination(self) -> None:
        module = _load_router_module()
        service = _FakeSyncService()
        module.jjc_match_data_sync_service = service

        response = await module.list_jjc_sync_queue(status="  ", page=2, page_size=20)

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(service.queue_calls, [{
            "status": None,
            "mode": None,
            "server": None,
            "name": None,
            "page": 2,
            "page_size": 20,
        }])
        self.assertIn("has_more", response["data"])
        self.assertTrue(response["data"]["has_more"])

    async def test_queue_trims_server_and_name_search(self) -> None:
        module = _load_router_module()
        service = _FakeSyncService()
        module.jjc_match_data_sync_service = service

        response = await module.list_jjc_sync_queue(
            status="queued",
            mode=" incremental ",
            server=" 梦江南 ",
            name=" 角色A ",
            page=1,
            page_size=50,
        )

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(service.queue_calls, [{
            "status": "queued",
            "mode": "incremental",
            "server": "梦江南",
            "name": "角色A",
            "page": 1,
            "page_size": 50,
        }])

    async def test_queue_reports_has_more_false_on_last_page(self) -> None:
        module = _load_router_module()
        service = _FakeSyncService()
        module.jjc_match_data_sync_service = service

        response = await module.list_jjc_sync_queue(status="queued", page=5, page_size=20)

        self.assertEqual(response["status_code"], 0)
        self.assertFalse(response["data"]["has_more"])

    async def test_workers_accepts_sync_service_method(self) -> None:
        module = _load_router_module()

        response = await module.list_jjc_sync_workers()

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["data"]["items"][0]["worker_id"], "worker-1")

    async def test_service_error_payload_returns_error_response(self) -> None:
        module = _load_router_module()

        class ErrorService:
            async def queue_status(self) -> Dict[str, Any]:
                return {"error": True, "message": "queue_down"}

        module.jjc_match_data_sync_service = ErrorService()

        response = await module.get_jjc_sync_status()

        self.assertEqual(response["status_code"], 1)
        self.assertEqual(response["status_msg"], "queue_down")
        self.assertEqual(response["data"], {"error": True, "message": "queue_down"})

    async def test_service_error_without_message_uses_generic_status(self) -> None:
        module = _load_router_module()

        class ErrorService:
            async def queue_status(self) -> Dict[str, Any]:
                return {"error": True}

        module.jjc_match_data_sync_service = ErrorService()

        response = await module.get_jjc_sync_status()

        self.assertEqual(response["status_code"], 1)
        self.assertEqual(response["status_msg"], "sync_service_error")
        self.assertEqual(response["data"], {"error": True})


if __name__ == "__main__":
    unittest.main()
