"""Pure domain rules for JX3 season timestamps."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_season_start_timestamp(season_start_str: str) -> int:
    """将 "2026-04-24" 格式的日期字符串转为 Unix 时间戳（秒）。

    使用北京时间（UTC+8）。
    """
    beijing_tz = timezone(timedelta(hours=8))
    dt = datetime.strptime(season_start_str, "%Y-%m-%d").replace(tzinfo=beijing_tz)
    return int(dt.timestamp())


__all__ = ["parse_season_start_timestamp"]
