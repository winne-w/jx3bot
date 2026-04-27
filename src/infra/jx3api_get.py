from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from cacheout import Cache

from src.infra.http_client import HttpClient

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

try:
    import config as cfg
except Exception:  # pragma: no cover
    cfg = None  # type: ignore


_server_data_cache: dict | None = None
_server_data_file = "server_data.json"

_cache_ttl_seconds = int(getattr(cfg, "SESSION_data", 720) if cfg else 720)
_cache = Cache(maxsize=256, ttl=_cache_ttl_seconds, timer=time.time, default=None)


def _extract_server_items(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        data = payload.get("data", [])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _load_server_data_cache_if_needed() -> bool:
    global _server_data_cache

    if _server_data_cache is not None:
        return True

    try:
        if os.path.exists(_server_data_file):
            with open(_server_data_file, "r", encoding="utf-8") as f:
                _server_data_cache = json.load(f)
            server_items = _extract_server_items(_server_data_cache)
            logger.info(f"jx3api_get server data 已加载: file={_server_data_file} count={len(server_items)}")
            return True

        logger.warning("jx3api_get server data 文件不存在: {}", _server_data_file)
        return False
    except Exception as exc:
        logger.warning("jx3api_get 读取服务器数据失败: {}", exc)
        return False


async def has_server_catalog() -> bool:
    if not _load_server_data_cache_if_needed():
        return False
    return len(_extract_server_items(_server_data_cache)) > 0


async def get(
    url: str,
    server: Optional[str] = None,
    name: Optional[str] = None,
    token: Optional[str] = None,
    ticket: Optional[str] = None,
    zili: Optional[str] = None,
) -> dict:
    if name is not None:
        name = (
            name.replace("[", "")
            .replace("]", "")
            .replace("&#91;", "")
            .replace("&#93;", "")
            .replace(" ", "")
        )

    params: dict[str, str] = {}
    if server:
        params["server"] = server
    if name:
        params["name"] = name
    if token:
        params["token"] = token
    if ticket:
        params["ticket"] = ticket
    if zili:
        params["class"] = zili

    cache_key = f"{url}{server}{name}"
    cache_data = _cache.get(cache_key)
    if cache_data:
        logger.debug("jx3api_get cache hit: {}", cache_key)
        return cache_data

    http_client = HttpClient(timeout=30.0, retries=2, backoff_seconds=0.5, verify=False)
    data = await http_client.arequest_json("GET", url, params=params, verify=False)
    if isinstance(data, dict) and not data.get("error"):
        _cache.set(cache_key, data)
    return data


async def idget(server_name: str) -> bool:
    global _server_data_cache

    normalized_name = (server_name or "").strip()
    if not normalized_name:
        logger.warning("jx3api_get idget 收到空区服名: raw={}", server_name)
        return False

    if not _load_server_data_cache_if_needed():
        return False

    try:
        server_items = _extract_server_items(_server_data_cache)
        if not server_items:
            logger.warning("jx3api_get server data 为空，跳过严格区服校验: file={}", _server_data_file)
            return False
        for server in server_items:
            if server.get("server") == normalized_name:
                return True
        sample_servers = [item.get("server") for item in server_items[:10] if item.get("server")]
        logger.warning(f"jx3api_get 未匹配到区服: query={normalized_name} sample_servers={sample_servers}")
        return False
    except Exception as exc:
        logger.warning("jx3api_get 解析服务器数据失败: {}", exc)
        return False

