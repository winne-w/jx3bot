import unittest
from pathlib import Path


class TestJjcRankingStatsFrontendCopy(unittest.TestCase):
    def test_peak_game_labels_use_14_day_window(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")

        self.assertIn("14日游戏内分数排名", content)
        self.assertIn("14日游戏最高分排名", content)
        self.assertIn("回溯前 14 天本地已收录的 3v3 对局", content)
        self.assertIn("正在加载14日最高分心法分布...", content)
        self.assertIn("14日最高分心法分布加载完成", content)
        self.assertIn("加载14日最高分心法分布失败", content)
        self.assertIn("_14日游戏最高分排名", content)

    def test_peak_game_detail_uses_dedicated_details_api(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")

        self.assertIn("function buildPeakDetailsUrl(timestamp, scoreType, rangeKey, kungfu)", content)
        self.assertIn("currentOuterTab === \"peak-game\"", content)
        self.assertIn("buildPeakDetailsUrl(currentStatsTimestamp, \"game\", rangeKey, kungfu)", content)


if __name__ == "__main__":
    unittest.main()
