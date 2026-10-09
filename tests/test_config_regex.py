from __future__ import annotations

import re
import unittest

import config


class ConfigRegexTests(unittest.TestCase):
    def test_jjc_ranking_accepts_tag_in_any_option_position(self) -> None:
        pattern = config.REGEX_PATTERNS["竞技排名"]
        for message in (
            "竞技排名 tag=40",
            "竞技排名统计 tag=40 缓存心法",
            "竞排名 拆分 tag=40 橙武占比 debug",
            "  竞技排名统计\t缓存心法 DEBUG tag=40  ",
        ):
            with self.subTest(message=message):
                self.assertIsNotNone(re.match(pattern, message))

    def test_jjc_ranking_routes_invalid_tags_to_usage_handler(self) -> None:
        pattern = config.REGEX_PATTERNS["竞技排名"]
        for value in ("", " 缓存心法", "abc", "-1", "0", "1.5", "40 tag=41"):
            with self.subTest(value=value):
                self.assertIsNotNone(re.match(pattern, "竞技排名 tag=" + value))

    def test_jjc_ranking_rejects_unrelated_options_with_tag(self) -> None:
        pattern = config.REGEX_PATTERNS["竞技排名"]
        for message in ("竞技排名 tag=40 无关", "竞排名 不缓存心法 tag=40"):
            with self.subTest(message=message):
                self.assertIsNone(re.match(pattern, message))

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
