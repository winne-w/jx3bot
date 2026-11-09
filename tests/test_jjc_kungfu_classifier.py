"""A01-A04/A07: fixtures freeze existing main-kungfu decisions."""
import copy
import unittest

from src.services.jx3.jjc_kungfu_classifier import select_kungfu

MAPPING = {"bingxin": "冰心诀", "yunchang": "云裳心经", "dujing": "毒经"}


def indicator(*metrics):
    return {"role_info": {"role_id": "role-a", "global_role_id": "SK01-role-a"},
            "indicator": [{"type": "3c", "metrics": list(metrics)}]}


def metric(kungfu, wins, total=100, items=None, pvp_type=3):
    return {"kungfu": kungfu, "win_count": wins, "total_count": total,
            "items": [1] if items is None else items, "pvp_type": pvp_type}


def wins(*kungfus):
    return [{"won": True, "kungfu": name} for name in kungfus]


class KungfuClassifierTests(unittest.TestCase):
    def select(self, data=None, matches=None):
        return select_kungfu(data or {}, matches or [], MAPPING)

    def test_indicator_uses_wins_not_total_and_ignores_empty_items_or_other_mode(self):
        data = indicator(metric("yunchang", 10, total=1000),
                         metric("bingxin", 20, total=100),
                         metric("dujing", 999, items=[]),
                         metric("dujing", 1000, pvp_type=2))
        result = self.select(data)
        self.assertEqual(result["kungfu"], "冰心诀")
        self.assertEqual(result["kungfu_pinyin"], "bingxin")
        self.assertEqual(result["kungfu_selected_source"], "indicator")

    def test_equal_indicator_win_count_keeps_first_metric_even_if_total_is_higher(self):
        result = self.select(indicator(metric("bingxin", 10, total=20),
                                       metric("yunchang", 10, total=200)))
        self.assertEqual(result["kungfu"], "冰心诀")

    def test_ten_recent_wins_override_old_indicator_main_kungfu(self):
        matches = wins(*(["bingxin"] * 6 + ["yunchang"] * 4))
        result = self.select(indicator(metric("yunchang", 100)), matches)
        self.assertEqual(result["kungfu"], "冰心诀")
        self.assertEqual(result["kungfu_indicator"], "云裳心经")
        self.assertEqual(result["kungfu_match_history"], "冰心诀")
        self.assertEqual(result["kungfu_selected_source"], "match_history")
        self.assertEqual(len(result["match_history_win_samples"]), 10)

    def test_tied_recent_wins_choose_first_occurrence(self):
        result = self.select(indicator(metric("yunchang", 100)),
                             wins(*(["bingxin", "yunchang"] * 5)))
        self.assertEqual(result["kungfu"], "冰心诀")

    def test_matching_recent_and_indicator_preserves_indicator_source(self):
        result = self.select(indicator(metric("bingxin", 100)), wins(*(["bingxin"] * 10)))
        self.assertEqual(result["kungfu_selected_source"], "indicator")
        self.assertEqual(result["kungfu_match_history"], "冰心诀")

    def test_fewer_than_ten_wins_keeps_indicator_without_season_field(self):
        data = indicator(metric("yunchang", 100))
        result = self.select(data, wins(*(["bingxin"] * 9)))
        self.assertNotIn("season_id", data)
        self.assertEqual(result["kungfu"], "云裳心经")
        self.assertEqual(result["kungfu_selected_source"], "indicator")
        self.assertIsNone(result["kungfu_match_history"])
        self.assertEqual(result["match_history_win_samples"], [])

    def test_only_first_forty_matches_and_first_ten_valid_wins_count(self):
        losses = [{"won": False, "kungfu": "dujing"} for _ in range(31)]
        result = self.select(indicator(metric("yunchang", 100)),
                             losses + wins(*(["bingxin"] * 10)))
        self.assertEqual(result["match_history_checked"], 40)
        self.assertEqual(result["kungfu"], "云裳心经")
        result = self.select({}, wins(*(["bingxin"] * 10 + ["yunchang"] * 30)))
        self.assertEqual(result["kungfu"], "冰心诀")
        self.assertEqual(result["match_history_win_samples"], ["bingxin"] * 10)

    def test_missing_win_marker_or_kungfu_does_not_count_as_valid_win(self):
        matches = [{"won": 1, "kungfu": "bingxin"}, {"won": True},
                   {"kungfu": "bingxin"}] + wins(*(["bingxin"] * 9))
        result = self.select(indicator(metric("yunchang", 100)), matches)
        self.assertEqual(result["kungfu"], "云裳心经")

    def test_history_can_choose_without_indicator_or_auxiliary_metadata(self):
        result = self.select({}, wins(*(["bingxin"] * 10)))
        self.assertEqual(result["kungfu"], "冰心诀")
        self.assertEqual(result["kungfu_selected_source"], "match_history")
        self.assertIsNone(result["kungfu_indicator"])

    def test_empty_inputs_produce_no_selected_name(self):
        result = self.select()
        self.assertIsNone(result["kungfu"])
        self.assertEqual(result["match_history_checked"], 0)

    def test_classifier_does_not_mutate_inputs(self):
        data = indicator(metric("bingxin", 10))
        matches = wins(*(["bingxin"] * 10))
        before = copy.deepcopy((data, matches))
        self.select(data, matches)
        self.assertEqual((data, matches), before)
