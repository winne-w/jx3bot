"""Tests for src.domain.kungfu_catalog and tank-lane accounting."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import config
from src.domain.kungfu_catalog import (
    AMBIGUOUS_KUNGFU_ALIASES,
    KUNGFU_ALIASES,
    KUNGFU_BY_ID,
    KUNGFU_BY_NAME,
    KUNGFU_BY_PINYIN,
    KUNGFU_CATALOG,
    KungfuAliasError,
    KungfuSpec,
    build_kungfu_meta,
    category_for_name,
    dps_names,
    get_jjc_catalog_specs,
    healer_names,
    name_by_id,
    resolve_kungfu_alias,
    tank_names,
)
from src.services.jx3.jjc_kungfu_meta import get_jjc_kungfu_catalog
from src.services.jx3.jjc_ranking import JjcRankingService


EXPECTED_TANK_NAMES = {"铁牢律", "洗髓经", "铁骨衣", "明尊琉璃体"}
EXPECTED_HEALER_NAMES = {"离经易道", "云裳心经", "补天诀", "相知", "灵素"}


def _load_stats_router_module() -> Any:
    """Load jjc_ranking_stats router with minimal stubs for pure helper tests."""
    saved: Dict[str, Any] = {}
    stub_names = (
        "fastapi",
        "nonebot",
        "src.api.response",
        "src.services.jx3.singletons",
        "src.storage.mongo_repos.jjc_ranking_stats_repo",
    )
    for mod_name in stub_names:
        saved[mod_name] = sys.modules.get(mod_name)

    try:
        class _FakeRouter:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def get(self, *args: Any, **kwargs: Any) -> Any:
                return lambda fn: fn

            def post(self, *args: Any, **kwargs: Any) -> Any:
                return lambda fn: fn

        fastapi_mod = types.ModuleType("fastapi")
        fastapi_mod.APIRouter = _FakeRouter
        fastapi_mod.Body = lambda default=None, **kwargs: default
        fastapi_mod.Query = lambda default=..., **kwargs: default
        sys.modules["fastapi"] = fastapi_mod

        nonebot_mod = types.ModuleType("nonebot")
        nonebot_mod.logger = types.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None
        )
        sys.modules["nonebot"] = nonebot_mod

        api_response_mod = types.ModuleType("src.api.response")
        api_response_mod.success_response = lambda data: {"status_code": 0, "data": data}
        api_response_mod.error_response = lambda msg, **kw: {"status_code": 1, "status_msg": msg}
        sys.modules["src.api.response"] = api_response_mod

        singletons_mod = types.ModuleType("src.services.jx3.singletons")
        singletons_mod.jjc_ranking_inspect_service = object()
        sys.modules["src.services.jx3.singletons"] = singletons_mod

        repo_mod = types.ModuleType("src.storage.mongo_repos.jjc_ranking_stats_repo")
        repo_mod.JjcRankingStatsRepo = object
        repo_mod.EquipmentSnapshotError = type("EquipmentSnapshotError", (Exception,), {})
        sys.modules["src.storage.mongo_repos.jjc_ranking_stats_repo"] = repo_mod

        module_path = Path(__file__).resolve().parents[1] / "src" / "api" / "routers" / "jjc_ranking_stats.py"
        spec = importlib.util.spec_from_file_location("jjc_ranking_stats_catalog_test", str(module_path))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for mod_name, original in saved.items():
            if original is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = original


class TestDomainKungfuCatalog(unittest.TestCase):
    def test_catalog_contains_all_33_kungfus_with_unique_keys(self) -> None:
        self.assertEqual(len(KUNGFU_CATALOG), 33)
        self.assertEqual(len(KUNGFU_BY_NAME), 33)
        self.assertEqual(len(KUNGFU_BY_ID), 33)
        self.assertEqual(len(KUNGFU_BY_PINYIN), 33)
        self.assertEqual(len(KUNGFU_ALIASES), 33)
        for spec in KUNGFU_CATALOG:
            self.assertIsInstance(spec, KungfuSpec)
            self.assertIs(KUNGFU_BY_NAME[spec.name], spec)
            self.assertIs(KUNGFU_BY_ID[spec.id], spec)
            self.assertIs(KUNGFU_BY_PINYIN[spec.pinyin], spec)

    def test_jjc_catalog_has_32_specs_and_excludes_xisui(self) -> None:
        jjc_specs = get_jjc_catalog_specs()
        self.assertEqual(len(jjc_specs), 32)
        self.assertEqual([spec.display_order for spec in jjc_specs], list(range(1, 33)))
        self.assertNotIn("洗髓经", {spec.name for spec in jjc_specs})
        self.assertEqual(KUNGFU_BY_NAME["洗髓经"].id, 10002)
        self.assertEqual(KUNGFU_BY_NAME["洗髓经"].pinyin, "xisui")
        self.assertEqual(KUNGFU_BY_NAME["洗髓经"].category, "tank")
        self.assertEqual(KUNGFU_BY_NAME["洗髓经"].school, "少林")
        self.assertEqual(KUNGFU_BY_NAME["洗髓经"].display_order, 33)
        self.assertFalse(KUNGFU_BY_NAME["洗髓经"].in_jjc_catalog)

        api_catalog = get_jjc_kungfu_catalog()
        self.assertEqual(len(api_catalog), 32)
        self.assertNotIn("洗髓经", {item["name"] for item in api_catalog})

    def test_four_tanks_and_wenshui_and_category_helpers(self) -> None:
        self.assertEqual(set(tank_names()), EXPECTED_TANK_NAMES)
        self.assertEqual(set(healer_names()), EXPECTED_HEALER_NAMES)
        self.assertEqual(len(dps_names()), 24)
        self.assertEqual(len(healer_names()) + len(dps_names()) + len(tank_names()), 33)

        self.assertEqual(KUNGFU_BY_PINYIN["wenshui"].name, "问水诀")
        self.assertEqual(KUNGFU_BY_PINYIN["wenshui"].id, 10144)
        self.assertEqual(KUNGFU_BY_PINYIN["wenshui"].category, "dps")

        for name in EXPECTED_TANK_NAMES:
            self.assertEqual(category_for_name(name), "tank")
        for name in EXPECTED_HEALER_NAMES:
            self.assertEqual(category_for_name(name), "healer")
        self.assertEqual(category_for_name("花间游"), "dps")
        self.assertIsNone(category_for_name("不存在心法"))
        self.assertIsNone(category_for_name(None))

        self.assertEqual(name_by_id(10026), "傲血战意")
        self.assertEqual(name_by_id("10026"), "傲血战意")
        self.assertEqual(name_by_id(10002), "洗髓经")
        self.assertIsNone(name_by_id(True))
        self.assertIsNone(name_by_id(999999))

    def test_config_kungfu_meta_matches_domain_catalog(self) -> None:
        expected_meta = build_kungfu_meta()
        self.assertEqual(len(expected_meta), 33)
        self.assertEqual(config.KUNGFU_META, expected_meta)
        self.assertIn("wenshui", config.KUNGFU_META)
        self.assertEqual(config.KUNGFU_META["xisui"], {"name": "洗髓经", "category": "tank"})
        self.assertEqual(config.KUNGFU_META["cangjian"], {"name": "山居剑意", "category": "dps"})

    def test_aliases_and_ambiguous_aliases(self) -> None:
        self.assertEqual(resolve_kungfu_alias("洗髓"), "洗髓经")
        self.assertEqual(resolve_kungfu_alias("傲血"), "傲血战意")
        self.assertIn("少林", AMBIGUOUS_KUNGFU_ALIASES)
        with self.assertRaises(KungfuAliasError):
            resolve_kungfu_alias("少林")

    def test_peak_kungfu_statistics_routes_tanks_to_tank_lane(self) -> None:
        router_mod = _load_stats_router_module()
        items = [
            {"kungfu": "离经易道", "score": 2500},
            {"kungfu": "花间游", "score": 2600},
            {"kungfu": "铁牢律", "score": 2400},
            {"kungfu": "明尊琉璃体", "score": 2450},
            {"kungfu": "洗髓经", "score": 2350},
            {"kungfu": "未知心法", "score": 2200},
        ]
        stats = router_mod._build_peak_kungfu_statistics(items)

        self.assertEqual(stats["healer"]["valid_count"], 1)
        self.assertEqual(stats["healer"]["distribution"], {"离经易道": 1})
        self.assertEqual(stats["tank"]["valid_count"], 3)
        self.assertEqual(
            stats["tank"]["distribution"],
            {"铁牢律": 1, "明尊琉璃体": 1, "洗髓经": 1},
        )
        self.assertEqual(stats["tank"]["min_score"], 2350)
        self.assertEqual(stats["dps"]["valid_count"], 2)
        self.assertNotIn("铁牢律", stats["dps"]["distribution"])
        self.assertNotIn("明尊琉璃体", stats["dps"]["distribution"])
        self.assertNotIn("洗髓经", stats["dps"]["distribution"])

    def test_count_kungfu_by_rank_places_tanks_in_tank_lane(self) -> None:
        service = JjcRankingService(
            token="",
            ticket="",
            jjc_query_url="",
            arena_time_tag_url="",
            arena_ranking_url="",
            match_detail_url="",
            jjc_ranking_cache_duration=60,
            kungfu_cache_duration=60,
            current_season="测试赛季",
            current_season_start="2026-11-05",
            kungfu_healer_list=healer_names(),
            kungfu_dps_list=dps_names(),
            kungfu_pinyin_to_chinese={p: s.name for p, s in KUNGFU_BY_PINYIN.items()},
            tuilan_request=lambda url, params: {},
            defget_get=AsyncMock(return_value={}),
        )

        players = [
            {"personInfo": {"server": "梦江南", "roleName": "奶花A", "score": 2700}},
            {"personInfo": {"server": "梦江南", "roleName": "花间B", "score": 2650}},
            {"personInfo": {"server": "梦江南", "roleName": "铁牢C", "score": 2600}},
            {"personInfo": {"server": "梦江南", "roleName": "洗髓D", "score": 2550}},
        ]
        kungfu_by_name = {
            "奶花A": {"found": True, "kungfu": "离经易道"},
            "花间B": {"found": True, "kungfu": "花间游"},
            "铁牢C": {"found": True, "kungfu": "铁牢律"},
            "洗髓D": {"found": True, "kungfu": "洗髓经"},
        }

        async def fake_get_user_kungfu(
            server: str, name: str, **kwargs: Any
        ) -> Dict[str, Any]:
            return {"server": server, "name": name, **kungfu_by_name[name]}

        with patch.object(JjcRankingService, "get_user_kungfu", side_effect=fake_get_user_kungfu), \
             patch.object(JjcRankingService, "_enqueue_ranking_member_for_sync", new=AsyncMock(return_value=False)), \
             patch.object(config, "JJC_RANKING_KUNGFU_CACHE_ENABLED", 0), \
             patch.object(config, "JJC_KUNGFU_REFRESH_ENABLED", 0), \
             patch.object(config, "JJC_RANKING_LOCAL_WIN_EQUIPMENT_ENABLED", 0):
            result = asyncio.run(service.get_ranking_kungfu_data({"data": players}))

        top50 = result["kungfu_statistics"]["top_50"]
        self.assertEqual(top50["healer"]["valid_count"], 1)
        self.assertEqual(top50["dps"]["valid_count"], 1)
        self.assertEqual(top50["tank"]["valid_count"], 2)
        self.assertEqual(top50["tank"]["distribution"]["铁牢律"], 1)
        self.assertEqual(top50["tank"]["distribution"]["洗髓经"], 1)
        self.assertEqual(len(top50["tank"]["members"]["铁牢律"]), 1)
        self.assertEqual(top50["tank"]["members"]["铁牢律"][0]["rank"], 3)
        self.assertNotIn("铁牢律", top50["dps"]["distribution"])
        self.assertNotIn("洗髓经", top50["dps"]["distribution"])
        self.assertEqual(top50["total_valid_count"], 4)
        self.assertEqual(top50["invalid_count"], 0)
        self.assertEqual(top50["unknown_members"], [])


if __name__ == "__main__":
    unittest.main()
