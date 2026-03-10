from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.jx3.baizhan import BaizhanCachePaths, load_cached_baizhan_image_bytes, save_baizhan_cache


def _load_alias_module():
    if "aiohttp" not in sys.modules:
        aiohttp_stub = types.ModuleType("aiohttp")

        class _ClientSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

        aiohttp_stub.ClientSession = _ClientSession
        sys.modules["aiohttp"] = aiohttp_stub

    package_name = "src.plugins.wanbaolou"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "plugins" / "wanbaolou")]
        sys.modules[package_name] = package

    if f"{package_name}.config" not in sys.modules:
        config_module = types.ModuleType(f"{package_name}.config")

        class _Config:
            alias_refresh_minutes = 360
            alias_cache_path = "data/wanbaolou_alias_cache.json"

        config_module.config = _Config()
        sys.modules[f"{package_name}.config"] = config_module

    module_name = f"{package_name}.alias"
    if module_name in sys.modules:
        return sys.modules[module_name]

    alias_path = Path(__file__).resolve().parents[1] / "src" / "plugins" / "wanbaolou" / "alias.py"
    spec = importlib.util.spec_from_file_location(module_name, alias_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


alias = _load_alias_module()


class AliasCacheTests(unittest.TestCase):
    def test_load_cache_file_prefers_mongo_payload(self) -> None:
        with patch(
            "src.plugins.wanbaolou.alias.cache_entry_storage.get_payload",
            return_value={"alias_to_canonical": {"别名A": "原名A"}},
        ):
            items = asyncio.run(alias._load_cache_file("unused.json"))
        self.assertEqual(items, [{"name": "别名A", "showName": "原名A"}])


class BaizhanCacheTests(unittest.TestCase):
    def test_load_cached_baizhan_image_bytes_prefers_mongo_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "baizhan_latest.png"
            image_path.write_bytes(b"img-bytes")
            paths = BaizhanCachePaths(image_path=str(image_path), data_path=str(Path(tmpdir) / "baizhan_data.json"))
            with patch(
                "src.services.jx3.baizhan.cache_entry_storage.get_payload",
                return_value={"start_timestamp": 1, "end_timestamp": 4_102_444_800, "result": {}},
            ):
                image_bytes = load_cached_baizhan_image_bytes(paths, now_ts=1_900_000_000)
        self.assertEqual(image_bytes, b"img-bytes")

    def test_save_baizhan_cache_backfills_mongo_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = BaizhanCachePaths(
                image_path=str(Path(tmpdir) / "baizhan_latest.png"),
                data_path=str(Path(tmpdir) / "baizhan_data.json"),
            )
            with patch("src.services.jx3.baizhan.cache_entry_storage.upsert_payload") as upsert_mock:
                save_baizhan_cache(
                    paths,
                    result={"start_timestamp": 1, "end_timestamp": 4_102_444_800},
                    image_bytes=b"img-bytes",
                )
        upsert_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
