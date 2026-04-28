from __future__ import annotations

from typing import Any, Set

from nonebot import logger

from src.infra.mongo import get_db
from src.services.jx3.singletons import group_config_repo
from src.storage.mongo_repos.status_cache_repo import StatusCacheRepo


def _repo() -> StatusCacheRepo:
    return StatusCacheRepo(db=get_db())


def load_groups() -> dict[str, Any]:
    return group_config_repo.load()


def save_groups(cfg: dict[str, Any]) -> None:
    group_config_repo.save(cfg)


class CacheManager:
    @staticmethod
    async def save_cache(data: Any, cache_name: str) -> bool:
        try:
            await _repo().save(cache_name, data)
            return True
        except Exception as exc:
            logger.warning("保存缓存失败({}): {}", cache_name, exc)
            return False

    @staticmethod
    async def load_cache(cache_name: str, default: Any = None) -> Any:
        try:
            return await _repo().load(cache_name, default)
        except Exception as exc:
            logger.warning("读取缓存失败({}): {}", cache_name, exc)
            return default


async def save_id_set(ids: Set[str], cache_name: str) -> bool:
    return await CacheManager.save_cache({"ids": list(ids)}, cache_name)


async def load_id_set(cache_name: str) -> Set[str]:
    data = await CacheManager.load_cache(cache_name, {"ids": []})
    return set(data.get("ids", []))
