from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JjcCacheRepo:
    jjc_ranking_cache_file: str
    jjc_ranking_cache_duration: int
    kungfu_cache_duration: int

    def load_ranking_cache(self) -> dict[str, Any] | None:
        if not os.path.exists(self.jjc_ranking_cache_file):
            return None
        try:
            with open(self.jjc_ranking_cache_file, "r", encoding="utf-8") as file_handle:
                cached_data = json.load(file_handle)
        except Exception as exc:
            logger.warning(f"读取竞技场排行榜缓存失败: file={self.jjc_ranking_cache_file} error={exc}")
            return None

        current_time = time.time()
        cache_time = cached_data.get("cache_time", 0)
        if current_time - cache_time < self.jjc_ranking_cache_duration:
            logger.info("使用文件缓存的竞技场排行榜数据")
            return cached_data.get("data")
        logger.info("竞技场排行榜文件缓存已过期")
        return None

    def save_ranking_cache(self, ranking_result: dict[str, Any]) -> None:
        cache_dir = os.path.dirname(self.jjc_ranking_cache_file)
        os.makedirs(cache_dir, exist_ok=True)
        try:
            with open(self.jjc_ranking_cache_file, "w", encoding="utf-8") as file_handle:
                json.dump(
                    {
                        "cache_time": ranking_result.get("cache_time", time.time()),
                        "data": ranking_result,
                    },
                    file_handle,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"竞技场排行榜数据已保存到文件缓存: {self.jjc_ranking_cache_file}")
        except Exception as exc:
            logger.warning(f"保存竞技场排行榜缓存失败: file={self.jjc_ranking_cache_file} error={exc}")

    def kungfu_cache_path(self, server: str, name: str) -> str:
        cache_dir = "data/cache/kungfu"
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"{server}_{name}.json")

    def load_kungfu_cache(self, server: str, name: str) -> dict[str, Any] | None:
        cache_file = self.kungfu_cache_path(server, name)
        if not os.path.exists(cache_file):
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as file_handle:
                cached_data = json.load(file_handle)
        except Exception as exc:
            logger.warning(f"读取心法缓存失败: file={cache_file} error={exc}")
            return None

        cache_time = cached_data.get("cache_time", 0)
        kungfu_value = cached_data.get("kungfu")

        if kungfu_value not in [None, ""]:
            current_time = time.time()
            if cache_time and current_time - cache_time < self.kungfu_cache_duration:
                return cached_data

            cache_dt = datetime.fromtimestamp(cache_time).strftime("%Y-%m-%d %H:%M:%S") if cache_time else "未知"
            logger.info(
                f"心法缓存过期，重新请求: server={server} name={name} cache_time={cache_dt}"
            )
        else:
            logger.info(f"心法缓存为空，重新请求: server={server} name={name}")

        return None

    def save_kungfu_cache(self, server: str, name: str, result: dict[str, Any]) -> None:
        cache_file = self.kungfu_cache_path(server, name)
        try:
            with open(cache_file, "w", encoding="utf-8") as file_handle:
                json.dump(result, file_handle, ensure_ascii=False, indent=2)
            logger.info(f"心法信息已更新缓存到: {cache_file}")
        except Exception as exc:
            logger.warning(f"保存心法缓存失败: file={cache_file} error={exc}")
