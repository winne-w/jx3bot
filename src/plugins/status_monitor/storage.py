from __future__ import annotations

import json
import os
from typing import Any, Set

from src.services.jx3.singletons import group_config_repo

CACHE_DIR = "data/cache"


def load_groups() -> dict[str, Any]:
    return group_config_repo.load()


def save_groups(cfg: dict[str, Any]) -> None:
    group_config_repo.save(cfg)


class CacheManager:
    @staticmethod
    def ensure_cache_dir() -> None:
        os.makedirs(CACHE_DIR, exist_ok=True)

    @staticmethod
    def save_cache(data: Any, cache_name: str) -> bool:
        try:
            CacheManager.ensure_cache_dir()
            cache_file = os.path.join(CACHE_DIR, f"{cache_name}.json")
            with open(cache_file, "w", encoding="utf-8") as file_handle:
                json.dump(data, file_handle)
            return True
        except Exception as exc:
            print(f"保存缓存失败({cache_name}): {str(exc)}")
            return False

    @staticmethod
    def load_cache(cache_name: str, default: Any = None) -> Any:
        try:
            cache_file = os.path.join(CACHE_DIR, f"{cache_name}.json")
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as file_handle:
                    return json.load(file_handle)
        except Exception as exc:
            print(f"读取缓存失败({cache_name}): {str(exc)}")
        return default


def save_id_set(ids: Set[str], cache_name: str) -> bool:
    return CacheManager.save_cache({"ids": list(ids)}, cache_name)


def load_id_set(cache_name: str) -> Set[str]:
    data = CacheManager.load_cache(cache_name, {"ids": []})
    return set(data.get("ids", []))
