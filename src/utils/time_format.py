from __future__ import annotations


def format_time_duration(seconds: float) -> str:
    if seconds < 0:
        return "0秒"

    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分钟")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}秒")

    return "".join(parts)
