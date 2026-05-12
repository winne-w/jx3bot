import unittest

from src.services.jx3.indicator_utils import find_3v3_indicator, select_best_3v3_metric


class TestIndicatorUtils(unittest.TestCase):
    def test_find_3v3_indicator_accepts_3c_and_3d(self):
        indicators = [
            {"type": "2d", "metrics": []},
            {"type": "3d", "metrics": [{"pvp_type": 3, "win_count": 2, "total_count": 3}]},
        ]

        self.assertEqual(find_3v3_indicator(indicators), indicators[1])

    def test_find_3v3_indicator_accepts_metric_pvp_type(self):
        indicators = [
            {"type": "custom", "metrics": [{"pvp_type": 3, "win_count": 2, "total_count": 3}]},
        ]

        self.assertEqual(find_3v3_indicator(indicators), indicators[0])

    def test_select_best_3v3_metric_matches_ranking_kungfu_rule(self):
        indicator = {
            "type": "3c",
            "metrics": [
                {"pvp_type": 3, "kungfu": "mowen", "win_count": 10, "total_count": 50, "items": [{"id": 1}]},
                {"pvp_type": 3, "kungfu": "xiangzhi", "win_count": 20, "total_count": 30, "items": [{"id": 1}]},
                {"pvp_type": 3, "kungfu": "ignored", "win_count": 100, "total_count": 100},
            ],
        }

        self.assertEqual(select_best_3v3_metric(indicator, require_items=True)["kungfu"], "xiangzhi")


if __name__ == "__main__":
    unittest.main()
