from __future__ import annotations

import json
import os
import time
from typing import Any

from nonebot import logger

from src.infra.http_client import HttpClient
from src.storage.singletons import cache_entry_storage

SERVER_MASTER_API_URL = "https://www.jx3api.com/data/server/master"
SERVER_MASTER_CACHE_FILE = "data/cache/server_master_cache.json"
SERVER_MASTER_CACHE_TTL = 7 * 24 * 60 * 60

_cache_loaded = False
_cache: dict[str, dict[str, Any]] = {}


def _normalize_server_key(name: str) -> str:
    return (name or "").strip()


def _load_cache() -> None:
    global _cache_loaded, _cache
    if _cache_loaded:
        return

    _cache_loaded = True
    mongo_payload = cache_entry_storage.get_payload("jx3", "server_master_aliases")
    if isinstance(mongo_payload, dict):
        _cache = mongo_payload
        return

    if not os.path.exists(SERVER_MASTER_CACHE_FILE):
        return

    try:
        with open(SERVER_MASTER_CACHE_FILE, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        if isinstance(data, dict):
            _cache = data
            cache_entry_storage.upsert_payload(
                "jx3",
                "server_master_aliases",
                _cache,
                expires_at=_expires_in(SERVER_MASTER_CACHE_TTL),
                meta={"source_file": SERVER_MASTER_CACHE_FILE},
            )
    except Exception as exc:
        logger.warning("区服简称缓存读取失败: {}", exc)
        _cache = {}


def _save_cache() -> None:
    cache_entry_storage.upsert_payload(
        "jx3",
        "server_master_aliases",
        _cache,
        expires_at=_expires_in(SERVER_MASTER_CACHE_TTL),
        meta={"source_file": SERVER_MASTER_CACHE_FILE},
    )
    try:
        os.makedirs(os.path.dirname(SERVER_MASTER_CACHE_FILE), exist_ok=True)
        with open(SERVER_MASTER_CACHE_FILE, "w", encoding="utf-8") as file_handle:
            json.dump(_cache, file_handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("区服简称缓存写入失败: {}", exc)


def _get_cached_master_name(query_name: str) -> str | None:
    _load_cache()
    key = _normalize_server_key(query_name)
    if not key:
        return None

    entry = _cache.get(key)
    if not isinstance(entry, dict):
        return None

    cached_at = int(entry.get("cached_at", 0) or 0)
    if int(time.time()) - cached_at >= SERVER_MASTER_CACHE_TTL:
        _cache.pop(key, None)
        _save_cache()
        return None

    master_name = entry.get("name")
    if isinstance(master_name, str) and master_name.strip():
        return master_name.strip()
    return None


def _cache_master_result(query_name: str, result_data: dict[str, Any]) -> None:
    _load_cache()
    now = int(time.time())
    master_name = (result_data.get("name") or "").strip()
    if not master_name:
        return

    entry_payload = {
        "name": master_name,
        "zone": result_data.get("zone", ""),
        "id": result_data.get("id", ""),
        "cached_at": now,
    }

    keys = {query_name, master_name}
    for alias in result_data.get("abbreviation", []) or []:
        if isinstance(alias, str) and alias.strip():
            keys.add(alias.strip())

    for key in keys:
        normalized_key = _normalize_server_key(key)
        if normalized_key:
            _cache[normalized_key] = entry_payload
    _save_cache()


async def resolve_master_server_name(server_name: str) -> str:
    """
    通过 jx3api 的 server/master 将区服简称转换为主区服全名。
    解析失败时返回原始输入，不中断主流程。
    """
    query_name = _normalize_server_key(server_name)
    if not query_name:
        return server_name

    cached_name = _get_cached_master_name(query_name)
    if cached_name:
        return cached_name

    http_client = HttpClient(timeout=15.0, retries=1, backoff_seconds=0.3, verify=False)
    response = await http_client.arequest_json(
        "GET",
        SERVER_MASTER_API_URL,
        params={"name": query_name},
        verify=False,
    )

    if not isinstance(response, dict):
        return server_name

    if response.get("code") != 200:
        return server_name

    data = response.get("data")
    if not isinstance(data, dict):
        return server_name

    master_name = (data.get("name") or "").strip()
    if not master_name:
        return server_name

    _cache_master_result(query_name, data)
    return master_name


def _expires_in(ttl_seconds: int):
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
