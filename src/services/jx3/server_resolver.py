from __future__ import annotations

import time
from typing import Any

from nonebot import logger

from config import API_URLS
from src.infra.http_client import HttpClient
from src.infra.mongo import get_db
from src.storage.mongo_repos.server_master_repo import ServerMasterCacheRepo

SERVER_MASTER_CACHE_TTL = 7 * 24 * 60 * 60


def _normalize_server_key(name: str) -> str:
    return (name or "").strip()


def _repo() -> ServerMasterCacheRepo:
    return ServerMasterCacheRepo(db=get_db(), ttl_seconds=SERVER_MASTER_CACHE_TTL)


async def _get_cached_master_name(query_name: str) -> str | None:
    key = _normalize_server_key(query_name)
    if not key:
        return None

    logger.info("[server_master] 查询 MongoDB 缓存: key={}", key)
    entry = await _repo().get(key)
    if entry is None:
        logger.info("[server_master] 缓存未命中: key={}", key)
        return None

    master_name = entry.get("name")
    if isinstance(master_name, str) and master_name.strip():
        logger.info("[server_master] 缓存命中: key={} -> master={}", key, master_name.strip())
        return master_name.strip()
    return None


async def _cache_master_result(query_name: str, result_data: dict[str, Any]) -> None:
    now = int(time.time())
    master_name = (result_data.get("name") or "").strip()
    if not master_name:
        logger.warning("[server_master] API 返回无 name 字段，跳过缓存: result={}", result_data)
        return

    entry_payload = {
        "name": master_name,
        "zone": result_data.get("zone", ""),
        "id": result_data.get("id", ""),
        "cached_at": now,
    }

    # 收集所有可映射到主服的 key：查询名、主服名、alias 列表、slave 列表
    keys = {query_name, master_name}
    for field in ("alias", "slave"):
        for item in (result_data.get(field) or []):
            if isinstance(item, str) and item.strip():
                keys.add(item.strip())

    repo = _repo()
    for alias_key in keys:
        normalized = _normalize_server_key(alias_key)
        if normalized:
            await repo.put(normalized, entry_payload)
    logger.info(
        "[server_master] 写入 MongoDB: query={}, keys={}, master={}, zone={}",
        query_name, list(keys), master_name, result_data.get("zone", ""),
    )


async def resolve_master_server_name(server_name: str) -> str:
    """
    通过 jx3api 的 server/master 将区服简称转换为主区服全名。
    解析失败时返回原始输入，不中断主流程。
    """
    query_name = _normalize_server_key(server_name)
    logger.info("[server_master] 开始解析区服: raw={} query={}", server_name, query_name)
    if not query_name:
        logger.warning("[server_master] 区服名为空，返回原始值")
        return server_name

    cached_name = await _get_cached_master_name(query_name)
    if cached_name:
        return cached_name

    logger.info("[server_master] 调用 API: url={} name={}", API_URLS["区服主服查询"], query_name)
    http_client = HttpClient(timeout=15.0, retries=1, backoff_seconds=0.3, verify=False)
    response = await http_client.arequest_json(
        "GET",
        API_URLS["区服主服查询"],
        params={"name": query_name},
        verify=False,
    )

    if not isinstance(response, dict):
        logger.warning("[server_master] API 返回非 dict: type={}", type(response))
        return server_name

    if response.get("code") != 200:
        logger.warning("[server_master] API 返回非 200: code={}", response.get("code"))
        return server_name

    data = response.get("data")
    if not isinstance(data, dict):
        logger.warning("[server_master] API data 不是 dict: type={}", type(data))
        return server_name

    master_name = (data.get("name") or "").strip()
    if not master_name:
        logger.warning("[server_master] API data.name 为空")
        return server_name

    await _cache_master_result(query_name, data)
    logger.info("[server_master] 解析成功: {} -> {}", server_name, master_name)
    return master_name
