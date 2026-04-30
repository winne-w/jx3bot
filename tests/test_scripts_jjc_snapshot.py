import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch


class TestClearScriptPrintCounts(unittest.TestCase):
    def setUp(self):
        # 动态导入，避免顶层导入触发 motor 依赖
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import clear_jjc_match_detail_snapshot_cache as mod
        self.mod = mod

    def test_print_counts_formats_correctly(self):
        counts = {
            "jjc_match_detail": 10,
            "jjc_equipment_snapshot": 5,
            "jjc_talent_snapshot": 3,
        }
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            self.mod._print_counts(counts, "测试")
        output = buf.getvalue()
        self.assertIn("jjc_match_detail", output)
        self.assertIn("10", output)
        self.assertIn("合计: 18", output)

    def test_print_counts_handles_missing_collection(self):
        counts = {
            "jjc_match_detail": -1,
            "jjc_equipment_snapshot": 0,
            "jjc_talent_snapshot": 0,
        }
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            self.mod._print_counts(counts, "测试")
        output = buf.getvalue()
        self.assertIn("(跳过)", output)
        self.assertIn("合计: 0", output)

    def test_get_mongo_uri_from_env(self):
        with patch.dict(os.environ, {"MONGO_URI": "mongodb://env/test"}, clear=True):
            uri = self.mod._get_mongo_uri()
            self.assertEqual(uri, "mongodb://env/test")

    def test_get_mongo_uri_missing_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("builtins.open", side_effect=FileNotFoundError):
                with self.assertRaises(RuntimeError):
                    self.mod._get_mongo_uri()


class TestVerifyScriptIterPlayers(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import verify_jjc_match_detail_snapshot_storage as mod
        self.mod = mod

    def test_iter_players_from_data_team_path(self):
        data = {
            "team1": {
                "players_info": [
                    {"role_name": "A", "equipment_snapshot_hash": "h1", "talent_snapshot_hash": "h2"},
                    {"role_name": "B", "equipment_snapshot_hash": "h3", "talent_snapshot_hash": "h4"},
                ]
            },
            "team2": {
                "players_info": [
                    {"role_name": "C", "equipment_snapshot_hash": "h5", "talent_snapshot_hash": "h6"},
                ]
            },
        }
        players = list(self.mod._iter_players(data))
        self.assertEqual(len(players), 3)
        self.assertEqual(players[0]["role_name"], "A")
        self.assertEqual(players[2]["role_name"], "C")

    def test_iter_players_from_data_detail_path(self):
        data = {
            "detail": {
                "team1": {
                    "players_info": [
                        {"role_name": "X", "equipment_snapshot_hash": "hx"},
                    ]
                },
                "team2": {
                    "players_info": [
                        {"role_name": "Y", "equipment_snapshot_hash": "hy"},
                    ]
                },
            }
        }
        players = list(self.mod._iter_players(data))
        self.assertEqual(len(players), 2)
        self.assertEqual(players[0]["role_name"], "X")
        self.assertEqual(players[1]["role_name"], "Y")

    def test_iter_players_data_detail_takes_priority(self):
        """data.detail.team* 和 data.team* 同时存在时，走 detail 路径。"""
        data = {
            "detail": {
                "team1": {
                    "players_info": [
                        {"role_name": "DetailA"},
                    ]
                },
            },
            "team1": {
                "players_info": [
                    {"role_name": "RootA"},
                ]
            },
        }
        players = list(self.mod._iter_players(data))
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0]["role_name"], "DetailA")

    def test_iter_players_empty_data(self):
        players = list(self.mod._iter_players({}))
        self.assertEqual(len(players), 0)

    def test_iter_players_missing_players_info(self):
        data = {"team1": {"other": "value"}, "team2": {}}
        players = list(self.mod._iter_players(data))
        self.assertEqual(len(players), 0)

    def test_iter_players_skips_non_dict_entries(self):
        data = {
            "team1": {
                "players_info": [
                    {"role_name": "A"},
                    "not-a-dict",
                    None,
                    123,
                    {"role_name": "B"},
                ]
            },
        }
        players = list(self.mod._iter_players(data))
        self.assertEqual(len(players), 2)
        self.assertEqual(players[0]["role_name"], "A")
        self.assertEqual(players[1]["role_name"], "B")

    def test_get_mongo_uri_from_env(self):
        with patch.dict(os.environ, {"MONGO_URI": "mongodb://env2/test"}, clear=True):
            uri = self.mod._get_mongo_uri()
            self.assertEqual(uri, "mongodb://env2/test")

    def test_get_mongo_uri_missing_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("builtins.open", side_effect=FileNotFoundError):
                with self.assertRaises(RuntimeError):
                    self.mod._get_mongo_uri()


if __name__ == "__main__":
    unittest.main()
