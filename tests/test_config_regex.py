from __future__ import annotations

import re
import unittest

import config


class ConfigRegexTests(unittest.TestCase):
    def test_jjc_ranking_accepts_cached_kungfu_option(self) -> None:
        pattern = config.REGEX_PATTERNS["竞技排名"]

        self.assertIsNotNone(re.match(pattern, "竞技排名统计 缓存心法"))
        self.assertIsNotNone(re.match(pattern, "竞技排名统计 拆分 缓存心法"))
        self.assertIsNotNone(re.match(pattern, "竞排名 缓存心法"))
        self.assertIsNotNone(re.match(pattern, "竞排名 缓存心法 橙武占比 debug"))

    def test_jjc_ranking_rejects_negative_cached_kungfu_option(self) -> None:
        pattern = config.REGEX_PATTERNS["竞技排名"]

        self.assertIsNone(re.match(pattern, "竞技排名统计 不缓存心法"))
        self.assertIsNone(re.match(pattern, "竞排名 不缓存心法"))


if __name__ == "__main__":
    unittest.main()
