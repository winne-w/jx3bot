import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.utils.time_utils import time_ago_fenzhong, time_ago_filter, timestamp_jjc


class TestTimeUtils(unittest.TestCase):
    def test_timestamp_jjc_default_and_custom_format(self) -> None:
        dt = datetime(2026, 11, 26, 14, 30, 45)
        ts = int(dt.timestamp())

        self.assertEqual(timestamp_jjc(ts), "2026-11-26 14:30:45")
        self.assertEqual(timestamp_jjc(ts, "%Y/%m/%d %H:%M"), "2026/11/26 14:30")

    def test_time_ago_fenzhong_special_and_relative_cases(self) -> None:
        fixed_now = datetime(2026, 11, 26, 12, 0, 0)
        self.assertEqual(time_ago_fenzhong(0), "被遗忘的时间")

        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromtimestamp.side_effect = datetime.fromtimestamp

            future_ts = int((fixed_now + timedelta(seconds=10)).timestamp())
            self.assertEqual(time_ago_fenzhong(future_ts), "未来时间")

            just_now_ts = int((fixed_now - timedelta(seconds=59)).timestamp())
            self.assertEqual(time_ago_fenzhong(just_now_ts), "刚刚")

            one_min_ts = int((fixed_now - timedelta(seconds=60)).timestamp())
            self.assertEqual(time_ago_fenzhong(one_min_ts), "01分钟前")

            hour_min_ts = int((fixed_now - timedelta(hours=2, minutes=5)).timestamp())
            self.assertEqual(time_ago_fenzhong(hour_min_ts), "02小时05分钟前")

            day_hour_min_ts = int(
                (fixed_now - timedelta(days=3, hours=4, minutes=9)).timestamp()
            )
            self.assertEqual(time_ago_fenzhong(day_hour_min_ts), "3天04小时09分钟前")

    def test_time_ago_filter_years_months_days_hours_minutes_and_boundaries(self) -> None:
        fixed_now = datetime(2026, 11, 26, 12, 0, 0)

        with patch("src.utils.time_utils.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromtimestamp.side_effect = datetime.fromtimestamp

            # Boundary: 0s and 59s -> 刚刚
            self.assertEqual(time_ago_filter(int(fixed_now.timestamp())), "刚刚")
            self.assertEqual(
                time_ago_filter(int((fixed_now - timedelta(seconds=59)).timestamp())),
                "刚刚",
            )
            # Future timestamp boundary -> 刚刚
            self.assertEqual(
                time_ago_filter(int((fixed_now + timedelta(seconds=30)).timestamp())),
                "刚刚",
            )

            # Minutes (< 1 hour)
            self.assertEqual(
                time_ago_filter(int((fixed_now - timedelta(seconds=60)).timestamp())),
                "1分钟前",
            )
            self.assertEqual(
                time_ago_filter(
                    int((fixed_now - timedelta(minutes=59, seconds=59)).timestamp())
                ),
                "59分钟前",
            )

            # Hours
            self.assertEqual(
                time_ago_filter(int((fixed_now - timedelta(hours=1)).timestamp())),
                "1小时前",
            )
            self.assertEqual(
                time_ago_filter(
                    int((fixed_now - timedelta(hours=5, minutes=40)).timestamp())
                ),
                "5小时前",
            )

            # 30 days -> 1月前 (not 1月0天前)
            self.assertEqual(
                time_ago_filter(int((fixed_now - timedelta(days=30)).timestamp())),
                "1月前",
            )

            # 365 days -> 1年前 (regression fix: previously returned 1年5天前)
            self.assertEqual(
                time_ago_filter(int((fixed_now - timedelta(days=365)).timestamp())),
                "1年前",
            )
            self.assertEqual(
                time_ago_filter(int((fixed_now - timedelta(days=730)).timestamp())),
                "2年前",
            )

            # 400 days -> 1年1月5天前 (365 + 30 + 5)
            self.assertEqual(
                time_ago_filter(int((fixed_now - timedelta(days=400)).timestamp())),
                "1年1月5天前",
            )
            self.assertEqual(
                time_ago_filter(
                    int((fixed_now - timedelta(days=400, hours=3)).timestamp())
                ),
                "1年1月5天3小时前",
            )


if __name__ == "__main__":
    unittest.main()
