from __future__ import annotations

import time
from typing import Any

from nonebot import logger

from src.infra.http_client import HttpClient
from src.infra.mongo import get_db
from src.storage.mongo_repos.server_master_repo import ServerMasterCacheRepo

SERVER_MASTER_API_URL = "https://www.jx3api.com/data/server/master"
SERVER_MASTER_CACHE_TTL = 7 * 24 * 60 * 60


def _normalize_server_key(name: str) -> str:
    return (name or "").strip()


def _repo() -> ServerMasterCacheRepo:
    return ServerMasterCacheRepo(db=get_db(), ttl_seconds=SERVER_MASTER_CACHE_TTL)


async def _get_cached_master_name(query_name: str) -> str | None:
    key = _normalize_server_key(query_name)
    if not key:
        return None

    entry = await _repo().get(key)
    if entry is None:
        return None

    master_name = entry.get("name")
    if isinstance(master_name, str) and master_name.strip():
        return master_name.strip()
    return None


async def _cache_master_result(query_name: str, result_data: dict[str, Any]) -> None:
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

    # 收集所有别名 keys
    keys = {query_name, master_name}
    for alias in result_data.get("abbreviation", []) or []:
        if isinstance(alias, str) and alias.strip():
            keys.add(alias.strip())

    repo = _repo()
    for alias_key in keys:
        normalized = _normalize_server_key(alias_key)
        if normalized:
            await repo.put(normalized, entry_payload)


async def resolve_master_server_name(server_name: str) -> str:
    """
    通过 jx3api 的 server/master 将区服简称转换为主区服全名。
    解析失败时返回原始输入，不中断主流程。
    """
    query_name = _normalize_server_key(server_name)
    if not query_name:
        return server_name

    cached_name = await _get_cached_master_name(query_name)
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

    await _cache_master_result(query_name, data)
    return master_name
