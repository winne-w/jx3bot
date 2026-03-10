from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")

    class _APIRouter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    def _query(default=None, **kwargs):
        return default

    class _FastAPI:
        def include_router(self, *args, **kwargs) -> None:
            return None

        def add_api_route(self, *args, **kwargs) -> None:
            return None

    fastapi_stub.FastAPI = _FastAPI
    fastapi_stub.APIRouter = _APIRouter
    fastapi_stub.Query = _query
    sys.modules["fastapi"] = fastapi_stub

from src.api.routers.jjc_ranking_stats import get_ranking_stats


class JjcRankingStatsApiTests(unittest.TestCase):
    def test_list_prefers_mongo(self) -> None:
        with patch("src.api.routers.jjc_ranking_stats.jjc_ranking_stats_storage.list_timestamps", return_value=[3, 2, 1]):
            response = asyncio.run(get_ranking_stats(action="list"))
        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["data"], [3, 2, 1])

    def test_read_falls_back_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            try:
                tmp_path = Path(tmpdir)
                (tmp_path / "data" / "jjc_ranking_stats").mkdir(parents=True)
                target = tmp_path / "data" / "jjc_ranking_stats" / "123.json"
                target.write_text(json.dumps({"generated_at": 123, "foo": "bar"}), encoding="utf-8")
                os.chdir(tmp_path)
                with patch("src.api.routers.jjc_ranking_stats.jjc_ranking_stats_storage.read", return_value=None):
                    response = asyncio.run(get_ranking_stats(action="read", timestamp="123"))
            finally:
                os.chdir(old_cwd)

        self.assertEqual(response["status_code"], 0)
        self.assertEqual(response["data"]["foo"], "bar")


if __name__ == "__main__":
    unittest.main()
