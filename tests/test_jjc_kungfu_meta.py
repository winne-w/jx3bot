from __future__ import annotations

import importlib
import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from config import KUNGFU_META


CURRENT_DISPLAY_KUNGFUS: Tuple[Tuple[str, int], ...] = (
    ("易筋经", 10003),
    ("紫霞功", 10014),
    ("太虚剑意", 10015),
    ("花间游", 10021),
    ("离经易道", 10028),
    ("傲血战意", 10062),
    ("铁牢律", 10061),
    ("冰心诀", 10081),
    ("云裳心经", 10080),
    ("毒经", 10175),
    ("补天诀", 10176),
    ("山居剑意", 10144),
    ("问水诀", 10145),
    ("天罗诡道", 10224),
    ("惊羽诀", 10225),
    ("分山劲", 10268),
    ("铁骨衣", 10267),
    ("笑尘诀", 10390),
    ("焚影圣诀", 10242),
    ("明尊琉璃体", 10243),
    ("莫问", 10447),
    ("相知", 10448),
    ("北傲诀", 10464),
    ("凌海诀", 10533),
    ("隐龙诀", 10585),
    ("无方", 10615),
    ("灵素", 10616),
    ("孤锋诀", 10698),
    ("山海心诀", 10756),
    ("周天功", 10786),
    ("太玄经", 10821),
    ("幽罗引", 10886),
)

FALLBACK_CATEGORY_BY_NAME = {
    "铁牢律": "tank",
    "问水诀": "dps",
    "铁骨衣": "tank",
    "明尊琉璃体": "tank",
}


class TestJjcKungfuMetaCatalog(unittest.TestCase):
    @staticmethod
    def _meta_module() -> Any:
        try:
            return importlib.import_module("src.services.jx3.jjc_kungfu_meta")
        except ModuleNotFoundError as error:
            if error.name == "src.services.jx3.jjc_kungfu_meta":
                raise AssertionError("JJC kungfu catalog service has not been implemented") from error
            raise

    @classmethod
    def _catalog(cls) -> List[Dict[str, Any]]:
        return cls._meta_module().get_jjc_kungfu_catalog()

    def test_catalog_migrates_every_currently_displayed_kungfu(self) -> None:
        catalog = self._catalog()

        self.assertEqual(
            [(entry["name"], entry["icon_id"]) for entry in catalog],
            list(CURRENT_DISPLAY_KUNGFUS),
        )
        for entry in catalog:
            self.assertEqual(entry["id"], entry["icon_id"])

    def test_catalog_entries_are_complete_positive_and_unique(self) -> None:
        catalog = self._catalog()

        self.assertEqual(len(catalog), len({entry["id"] for entry in catalog}))
        for entry in catalog:
            self.assertTrue({"id", "name", "category", "icon_id", "display_order"} <= entry.keys())
            self.assertIsInstance(entry["id"], int)
            self.assertGreater(entry["id"], 0)
            self.assertIsInstance(entry["icon_id"], int)
            self.assertGreater(entry["icon_id"], 0)
            self.assertTrue(entry["name"])
            self.assertTrue(entry["category"])

    def test_catalog_uses_config_names_and_categories_when_available(self) -> None:
        catalog_by_name = {entry["name"]: entry for entry in self._catalog()}
        config_by_name = {
            meta["name"]: meta
            for meta in KUNGFU_META.values()
            if isinstance(meta, dict)
            and isinstance(meta.get("name"), str)
            and meta["name"].strip()
            and isinstance(meta.get("category"), str)
            and meta["category"].strip()
        }

        missing_config_names = set()
        for name, _ in CURRENT_DISPLAY_KUNGFUS:
            with self.subTest(name=name):
                config_meta = config_by_name.get(name)
                if config_meta is None:
                    missing_config_names.add(name)
                    self.assertEqual(
                        catalog_by_name[name]["category"],
                        FALLBACK_CATEGORY_BY_NAME[name],
                    )
                else:
                    self.assertEqual(catalog_by_name[name]["name"], config_meta["name"])
                    self.assertEqual(catalog_by_name[name]["category"], config_meta["category"])
        self.assertEqual(missing_config_names, set(FALLBACK_CATEGORY_BY_NAME))

    def test_config_only_kungfus_do_not_enlarge_the_current_display_catalog(self) -> None:
        meta_module = self._meta_module()
        try:
            with patch.dict(
                KUNGFU_META,
                {"retired": {"name": "历史心法", "category": "dps"}},
            ):
                importlib.reload(meta_module)
                self.assertEqual(
                    [(entry["name"], entry["id"]) for entry in meta_module.get_jjc_kungfu_catalog()],
                    list(CURRENT_DISPLAY_KUNGFUS),
                )
        finally:
            importlib.reload(meta_module)

    def test_catalog_snapshots_config_metadata(self) -> None:
        with patch.dict(KUNGFU_META["lijing"], {"category": "mutated"}):
            catalog_by_name = {entry["name"]: entry for entry in self._catalog()}
            self.assertEqual(catalog_by_name["离经易道"]["category"], "healer")

    def test_invalid_config_categories_fall_back_without_changing_the_legacy_name(self) -> None:
        meta_module = self._meta_module()
        try:
            for category in ("", "invalid"):
                with self.subTest(category=category):
                    with patch.dict(KUNGFU_META["lijing"], {"category": category}):
                        importlib.reload(meta_module)
                        catalog_by_name = {
                            entry["name"]: entry for entry in meta_module.get_jjc_kungfu_catalog()
                        }
                        self.assertEqual(catalog_by_name["离经易道"]["name"], "离经易道")
                        self.assertEqual(catalog_by_name["离经易道"]["category"], "healer")
        finally:
            importlib.reload(meta_module)

    def test_config_name_is_stripped_before_joining_the_catalog(self) -> None:
        meta_module = self._meta_module()
        try:
            with patch.dict(
                KUNGFU_META["lijing"],
                {"name": " 离经易道 ", "category": "tank"},
            ):
                importlib.reload(meta_module)
                catalog_by_name = {
                    entry["name"]: entry for entry in meta_module.get_jjc_kungfu_catalog()
                }
                self.assertEqual(catalog_by_name["离经易道"]["name"], "离经易道")
                self.assertEqual(catalog_by_name["离经易道"]["category"], "tank")
        finally:
            importlib.reload(meta_module)

    def test_catalog_sort_order_is_stable_and_callers_cannot_mutate_it(self) -> None:
        catalog = self._catalog()

        self.assertEqual(
            [(entry["display_order"], entry["id"]) for entry in catalog],
            sorted((entry["display_order"], entry["id"]) for entry in catalog),
        )
        catalog[0]["name"] = "mutated"
        self.assertNotEqual(self._catalog()[0]["name"], "mutated")
