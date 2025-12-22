from __future__ import annotations

from datetime import datetime


def timestamp_jjc(timestamp: int, format: str = "%Y-%m-%d %H:%M:%S") -> str:
    dt_object = datetime.fromtimestamp(timestamp)
    return dt_object.strftime(format)


def time_ago_fenzhong(timestamp: int) -> str:
    if timestamp == 0:
        return "被遗忘的时间"

    now = datetime.now()
    then = datetime.fromtimestamp(timestamp)
    total_seconds = int((now - then).total_seconds())

    if total_seconds < 0:
        return "未来时间"

    if total_seconds < 60:
        return "刚刚"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    relative_time = []
    if days > 0:
        relative_time.append(f"{days}天")
    if hours > 0:
        relative_time.append(f"{hours:02d}小时")
    if minutes > 0:
        relative_time.append(f"{minutes:02d}分钟")

    return "".join(relative_time) + "前"


def time_ago_filter(timestamp: int) -> str:
    now = datetime.now()
    then = datetime.fromtimestamp(timestamp)
    time_difference = now - then

    years = time_difference.days // 365
    months = (time_difference.days % 365) // 30
    days = time_difference.days % 30
    hours = time_difference.seconds // 3600

    relative_time = []
    if years > 0:
        relative_time.append(f"{years}年")
    if months > 0:
        relative_time.append(f"{months}月")
    if days > 0:
        relative_time.append(f"{days}天")
    if hours > 0:
        relative_time.append(f"{hours}小时")
    return "".join(relative_time) + "前"

