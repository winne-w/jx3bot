import unittest

from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.weapon_quality import extract_member_weapon_name, extract_weapon_name, is_jjc_legendary_weapon


def _build_service() -> JjcRankingService:
    return JjcRankingService(
        token="",
        ticket="",
        jjc_query_url="",
        arena_time_tag_url="",
        arena_ranking_url="",
        match_detail_url="",
        jjc_ranking_cache_duration=0,
        kungfu_cache_duration=0,
        current_season="",
        current_season_start="",
        kungfu_healer_list=[],
        kungfu_dps_list=[],
        kungfu_pinyin_to_chinese={},
        tuilan_request=lambda url, params: {},
        defget_get=lambda **kwargs: {},
    )


class TestJjcWeaponQuality(unittest.TestCase):
    def test_allowlisted_quality_five_is_legendary(self) -> None:
        self.assertTrue(is_jjc_legendary_weapon("5", "钗蝶语双"))

    def test_non_allowlisted_quality_five_is_not_legendary(self) -> None:
        self.assertFalse(is_jjc_legendary_weapon("5", "江山赋·寻"))

    def test_quality_four_allowlisted_name_is_not_legendary(self) -> None:
        self.assertFalse(is_jjc_legendary_weapon("4", "钗蝶语双"))

    def test_missing_name_is_not_legendary(self) -> None:
        self.assertFalse(is_jjc_legendary_weapon("5", None))
        self.assertFalse(is_jjc_legendary_weapon("5", ""))

    def test_extract_weapon_name_from_dict(self) -> None:
        self.assertEqual(extract_weapon_name({"name": "钗蝶语双"}), "钗蝶语双")
        self.assertIsNone(extract_weapon_name(None))

    def test_extract_member_weapon_name_prefers_flat_field_and_supports_legacy_weapon(self) -> None:
        self.assertEqual(
            extract_member_weapon_name({"weapon_name": "钗蝶语双", "weapon": {"name": "江山赋·寻"}}),
            "钗蝶语双",
        )
        self.assertEqual(extract_member_weapon_name({"weapon": {"name": "钗蝶语双"}}), "钗蝶语双")


class TestJjcRankingSummaryWeaponQuality(unittest.TestCase):
    def test_summary_uses_weapon_name_allowlist_when_present(self) -> None:
        service = _build_service()
        payload = service._build_summary_payload({
            "generated_at": 1,
            "ranking_cache_time": 1,
            "default_week": 1,
            "current_season": "暗影千机",
            "week_info": "test",
            "kungfu_statistics": {
                "top_50": {
                    "total_players": 3,
                    "healer": {
                        "members": {
                            "云裳心经": [
                                {"weapon_quality": "5", "weapon_name": "钗蝶语双"},
                                {"weapon_quality": "5", "weapon_name": "江山赋·寻"},
                                {"weapon_quality": "4", "weapon_name": "钗蝶语双"},
                            ]
                        }
                    },
                    "dps": {"members": {}},
                }
            },
        })

        self.assertEqual(
            payload["kungfu_statistics"]["top_50"]["healer"]["legendary_count_map"]["云裳心经"],
            1,
        )

    def test_summary_requires_weapon_name(self) -> None:
        service = _build_service()
        payload = service._build_summary_payload({
            "generated_at": 1,
            "ranking_cache_time": 1,
            "default_week": 1,
            "current_season": "暗影千机",
            "week_info": "test",
            "kungfu_statistics": {
                "top_50": {
                    "total_players": 1,
                    "healer": {
                        "members": {
                            "云裳心经": [
                                {"weapon_quality": "5"},
                            ]
                        }
                    },
                    "dps": {"members": {}},
                }
            },
        })

        self.assertEqual(
            payload["kungfu_statistics"]["top_50"]["healer"]["legendary_count_map"]["云裳心经"],
            0,
        )

    def test_summary_uses_legacy_weapon_object_name_when_present(self) -> None:
        service = _build_service()
        payload = service._build_summary_payload({
            "generated_at": 1,
            "ranking_cache_time": 1,
            "default_week": 1,
            "current_season": "暗影千机",
            "week_info": "test",
            "kungfu_statistics": {
                "top_50": {
                    "total_players": 2,
                    "healer": {
                        "members": {
                            "云裳心经": [
                                {"weapon_quality": "5", "weapon": {"name": "钗蝶语双"}},
                                {"weapon_quality": "5", "weapon": {"name": "江山赋·寻"}},
                            ]
                        }
                    },
                    "dps": {"members": {}},
                }
            },
        })

        self.assertEqual(
            payload["kungfu_statistics"]["top_50"]["healer"]["legendary_count_map"]["云裳心经"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
