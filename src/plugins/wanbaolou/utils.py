from typing import Optional
from datetime import datetime, timedelta


def format_time_string(seconds: int) -> str:
    """将秒数转换为可读的时间字符串

    Args:
        seconds: 秒数

    Returns:
        str: 格式化后的时间字符串 (例如: "1小时30分钟")
    """
    if seconds < 60:
        return f"{seconds}秒"

    minutes = seconds // 60
    remaining_seconds = seconds % 60

    if minutes < 60:
        if remaining_seconds == 0:
            return f"{minutes}分钟"
        return f"{minutes}分钟{remaining_seconds}秒"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if hours < 24:
        if remaining_minutes == 0:
            return f"{hours}小时"
        return f"{hours}小时{remaining_minutes}分钟"

    days = hours // 24
    remaining_hours = hours % 24

    if remaining_hours == 0:
        return f"{days}天"
    return f"{days}天{remaining_hours}小时"


def save_image_cache(image_url: str, image_data: bytes, cache_dir: str = "image_cache") -> None:
    """保存图片到本地缓存

    Args:
        image_url: 图片URL
        image_data: 图片二进制数据
        cache_dir: 缓存目录
    """
    import os
    import hashlib

    # 创建缓存目录
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    # 使用URL的哈希作为文件名
    filename = hashlib.md5(image_url.encode()).hexdigest() + ".png"
    file_path = os.path.join(cache_dir, filename)

    # 保存图片
    with open(file_path, "wb") as f:
        f.write(image_data)