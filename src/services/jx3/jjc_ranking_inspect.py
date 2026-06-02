from __future__ import annotations

import asyncio
import copy
import inspect
import threading
import time
from weakref import WeakKeyDictionary
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from nonebot import logger

from src.services.jx3.jjc_cache_repo import JjcCacheRepo
from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.indicator_utils import parse_3v3_indicator
from src.services.jx3.kungfu import (
    extract_global_id_from_match_replay,
    merge_replay_global_ids_into_match_detail,
)
from src.services.jx3.match_history import MatchHistoryClient
from src.services.jx3.match_detail import MatchDetailClient, MatchDetailResponse
from src.services.jx3.match_replay import MatchReplayClient
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo
from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo


SYNCED_MATCH_PAGE_SYNC_PRIORITY = 2


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _extract_match_id(match: dict[str, Any]) -> Optional[int]:
    for key in ("match_id", "matchId", "matchID", "id"):
        value = _coerce_int(match.get(key))
        if value is not None:
            return value
    return None


def _extract_id_like_fields(match: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in match.items():
        if "id" not in str(key).lower():
            continue
        result[str(key)] = value
    return result


def _extract_grade_like_fields(match: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in match.items():
        key_text = str(key).lower()
        if "grade" in key_text or "rank" in key_text or "segment" in key_text:
            result[str(key)] = value
    return result


def _normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    if "·" in name:
        return name.split("·")[0]
    return name


def _pick_str(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_match_time(match: dict[str, Any]) -> Optional[int]:
    return _coerce_int(
        match.get("match_time")
        or match.get("matchTime")
        or match.get("start_time")
        or match.get("startTime")
        or match.get("time")
    )


def _extract_duration(match: dict[str, Any]) -> Optional[int]:
    duration = _coerce_int(match.get("duration") or match.get("fight_time") or match.get("fight_seconds"))
    if duration is not None:
        return duration
    start_time = _coerce_int(match.get("start_time") or match.get("startTime"))
    end_time = _coerce_int(match.get("end_time") or match.get("endTime"))
    if start_time and end_time and end_time >= start_time:
        return end_time - start_time
    return None


def _extract_avg_grade(match: dict[str, Any]) -> Optional[int]:
    return _coerce_int(
        match.get("avgGrade")
        or match.get("avg_grade")
        or match.get("grade")
        or match.get("segment")
        or match.get("level")
    )


def _extract_total_mmr(match: dict[str, Any]) -> Optional[int]:
    return _coerce_int(
        match.get("totalMmr")
        or match.get("total_mmr")
        or match.get("score")
        or match.get("mmr_total")
    )


def _parse_3v3_indicator(raw: dict[str, Any]) -> dict[str, Any]:
    return parse_3v3_indicator(raw)


def _extract_person_id_from_indicator(raw: dict[str, Any]) -> Optional[str]:
    data = raw.get("data") if isinstance(raw, dict) else None
    payload = data if isinstance(data, dict) else raw
    person_info = payload.get("person_info") if isinstance(payload, dict) else None
    if not isinstance(person_info, dict):
        return None
    return _pick_str(person_info.get("person_id"), person_info.get("personId"))


def normalize_recent_matches(
    raw_matches: list,
    *,
    kungfu_pinyin_to_chinese: dict[str, str],
    max_recent_matches: int = 20,
) -> list:
    """Convert raw match history items to the recent_matches shape used by the live path.

    Pure function: accepts kungfu_pinyin_to_chinese and max_recent_matches explicitly.
    Handles pvpType/pvp_type/type filtering, field aliases, Chinese kungfu translation,
    sort descending, truncation, and missing fields gracefully.
    """
    history_3v3: list = []
    for item in raw_matches:
        if not isinstance(item, dict):
            continue
        type_raw = None
        type_present = False
        for key in ("pvpType", "pvp_type", "type"):
            if key in item:
                type_raw = item[key]
                type_present = True
                break
        if type_present:
            pvp_type = _coerce_int(type_raw)
            if pvp_type != 3:
                continue
        match_id = _extract_match_id(item)
        match_time = _extract_match_time(item)
        kungfu_raw = item.get("kungfu") or item.get("kungfu_name")
        kungfu_cn = ""
        if kungfu_raw:
            kungfu_cn = kungfu_pinyin_to_chinese.get(str(kungfu_raw), str(kungfu_raw))
        history_3v3.append(
            {
                "match_id": match_id,
                "won": bool(item.get("won")),
                "kungfu": kungfu_cn,
                "avg_grade": _extract_avg_grade(item),
                "total_mmr": _extract_total_mmr(item),
                "mmr_delta": _coerce_int(item.get("mmr")),
                "mvp": bool(item.get("mvp")),
                "match_time": match_time,
                "start_time": _coerce_int(item.get("startTime") or item.get("start_time")) or match_time,
                "end_time": _coerce_int(item.get("endTime") or item.get("end_time")),
                "duration": _extract_duration(item),
            }
        )

    history_3v3.sort(key=lambda item: item.get("match_time") or item.get("start_time") or 0, reverse=True)
    return history_3v3[:max_recent_matches]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True)
class JjcRankingInspectService:
    ranking_service: JjcRankingService
    kungfu_cache_repo: JjcCacheRepo
    match_history_client: MatchHistoryClient
    match_detail_client: MatchDetailClient
    cache_repo: JjcInspectRepo
    tuilan_request: Callable[[str, dict[str, Any]], Any]
    role_indicator_fetcher: Callable[..., Optional[dict[str, Any]]]
    kungfu_pinyin_to_chinese: dict[str, str]
    match_replay_client: Optional[MatchReplayClient] = None
    match_detail_projection_service: Any = None
    match_detail_participant_projection_service: Any = None
    role_identity_repo: Any = None
    sync_repo: Any = None
    role_recent_ttl_seconds: int = 86400
    role_indicator_ttl_seconds: int = 86400
    max_recent_matches: int = 20
    _tuilan_query_locks: WeakKeyDictionary = field(default_factory=WeakKeyDictionary, init=False, repr=False)
    _tuilan_query_locks_guard: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _get_tuilan_query_lock(self, endpoint_key: str) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._tuilan_query_locks_guard:
            locks = self._tuilan_query_locks.get(loop)
            if locks is None:
                locks = {}
                self._tuilan_query_locks[loop] = locks
            lock = locks.get(endpoint_key)
            if lock is None:
                lock = asyncio.Lock()
                locks[endpoint_key] = lock
        return lock

    def _translate_kungfu_name(self, value: Any) -> str:
        text = _pick_str(value) or ""
        if not text:
            return ""
        return self.kungfu_pinyin_to_chinese.get(text, text)

    def _role_identity_repo(self) -> Any:
        return self.role_identity_repo or RoleIdentityRepo()

    def _sync_repo(self) -> Any:
        return self.sync_repo or JjcSyncRepo()

    @staticmethod
    def _serialize_identity(identity: dict[str, Any]) -> dict[str, Any]:
        identity_id = identity.get("_id") or identity.get("identity_id")
        result: dict[str, Any] = {}
        if identity_id is not None:
            result["identity_id"] = str(identity_id)
        for key in (
            "identity_key",
            "server",
            "name",
            "zone",
            "game_role_id",
            "global_id",
            "global_role_id",
            "role_id",
        ):
            value = identity.get(key)
            if value is not None:
                result[key] = str(value) if key.endswith("_id") else value
        return result

    @staticmethod
    def _serialize_sync_status(doc: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not doc:
            return {"exists": False, "status": "not_queued"}
        result = {
            "exists": True,
            "identity_id": str(doc.get("identity_id")) if doc.get("identity_id") is not None else None,
            "identity_key": doc.get("identity_key"),
            "status": doc.get("status"),
            "queued_at": doc.get("queued_at"),
            "queue_mode": doc.get("queue_mode"),
            "queue_source": doc.get("queue_source"),
            "priority": doc.get("priority"),
            "last_synced_at": doc.get("last_synced_at"),
            "latest_seen_match_time": doc.get("latest_seen_match_time"),
            "history_exhausted": doc.get("history_exhausted"),
            "last_error": doc.get("last_error"),
            "lease_owner": doc.get("lease_owner"),
            "lease_expires_at": doc.get("lease_expires_at"),
        }
        return result

    async def _serialize_sync_status_with_position(self, doc: Optional[dict[str, Any]]) -> dict[str, Any]:
        result = self._serialize_sync_status(doc)
        if doc and str(doc.get("status") or "") == "queued":
            sync_repo = self._sync_repo()
            if hasattr(sync_repo, "get_queue_position"):
                position = await sync_repo.get_queue_position(doc)
                if position is not None:
                    result["queue_position"] = position
        return result

    async def _resolve_synced_identity_only(self, *, server: str, name: str) -> Optional[dict[str, Any]]:
        repo = self._role_identity_repo()
        if hasattr(repo, "find_best_by_name_with_id"):
            return await repo.find_best_by_name_with_id(server, name)
        return await repo.resolve_best_identity_with_id(server=server, name=name)

    async def _find_synced_role_candidates(self, *, server: str, name: str, limit: int = 8) -> List[Dict[str, Any]]:
        repo = self._role_identity_repo()
        finder = getattr(repo, "find_synced_match_page_candidates", None)
        if not callable(finder):
            return []
        try:
            docs = await finder(server, name, limit=limit)
        except Exception as exc:
            logger.warning("JJC 已同步角色候选查询失败: server={} name={} error={}", server, name, exc)
            return []

        candidates: List[Dict[str, Any]] = []
        for doc in docs or []:
            if not isinstance(doc, dict):
                continue
            identity = self._serialize_identity(doc)
            candidate_server = _pick_str(doc.get("server"), identity.get("server")) or ""
            candidate_name = _normalize_name(_pick_str(doc.get("name"), identity.get("name")) or "")
            if not candidate_server or not candidate_name:
                continue
            reason = "same_name_other_server"
            if "@" in candidate_name:
                reason = "name_with_suffix"
            sync_doc = await self._sync_repo().get_queue_state_by_identity_id(doc.get("_id"))
            candidates.append({
                "player": {"server": candidate_server, "name": candidate_name},
                "identity": identity,
                "sync_status": await self._serialize_sync_status_with_position(sync_doc),
                "reason": reason,
            })
        return candidates

    async def resolve_synced_role(self, *, server: str, name: str) -> dict[str, Any]:
        """Resolve a role for the synced-match page using role_identities only."""
        identity = await self._resolve_synced_identity_only(server=server, name=name)
        if not identity:
            candidates = await self._find_synced_role_candidates(server=server, name=name)
            return {
                "error": True,
                "message": "role_identity_not_found",
                "player": {"server": server, "name": _normalize_name(name)},
                "candidates": candidates,
                "guidance": (
                    "如果目标角色暂未收录，可以搜索和他打过 3v3 的角色，"
                    "更新该角色对局后，系统会从对局详情里同步目标角色信息。"
                ),
            }
        sync_doc = await self._sync_repo().get_queue_state_by_identity_id(identity.get("_id"))
        sync_status = await self._serialize_sync_status_with_position(sync_doc)
        return {
            "player": {
                "server": identity.get("server") or server,
                "name": _normalize_name(_pick_str(identity.get("name")) or name),
            },
            "identity": self._serialize_identity(identity),
            "sync_status": sync_status,
        }

    async def get_synced_role_matches(
        self,
        *,
        server: str,
        name: str,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        phase_started_at = started_at
        resolved = await self.resolve_synced_role(server=server, name=name)
        resolve_ms = int((time.perf_counter() - phase_started_at) * 1000)
        if resolved.get("error"):
            logger.info(
                "JJC 已同步对局查询完成: server={} name={} page={} page_size={} elapsed_ms={} "
                "resolve_ms={} error={}".format(
                    server,
                    name,
                    page,
                    page_size,
                    int((time.perf_counter() - started_at) * 1000),
                    resolve_ms,
                    resolved.get("message") or resolved.get("error"),
                )
            )
            return resolved
        identity = resolved.get("identity") or {}
        phase_started_at = time.perf_counter()
        try:
            matches = await self.cache_repo.list_saved_local_3v3_matches_for_identity(
                identity_id=identity.get("identity_id"),
                identity_key=identity.get("identity_key"),
                server=identity.get("server") or server,
                name=identity.get("name") or name,
                global_id=identity.get("global_id"),
                global_role_id=identity.get("global_role_id"),
                role_id=identity.get("role_id"),
                game_role_id=identity.get("game_role_id"),
                page=page,
                page_size=page_size,
            )
        except Exception as exc:
            list_ms = int((time.perf_counter() - phase_started_at) * 1000)
            logger.warning(
                "JJC 已同步对局参与者投影查询失败: server={} name={} page={} page_size={} "
                "identity_id={} global_id={} list_ms={} error={}".format(
                    server,
                    name,
                    page,
                    page_size,
                    identity.get("identity_id"),
                    identity.get("global_id"),
                    list_ms,
                    exc,
                )
            )
            return {
                "error": True,
                "message": "match_participants_query_failed",
                "player": resolved.get("player"),
                "identity": identity,
                "sync_status": resolved.get("sync_status"),
            }
        list_ms = int((time.perf_counter() - phase_started_at) * 1000)
        logger.info(
            "JJC 已同步对局查询完成: server={} name={} page={} page_size={} elapsed_ms={} "
            "resolve_ms={} list_ms={} identity_id={} global_id={} total={} items={}".format(
                server,
                name,
                page,
                page_size,
                int((time.perf_counter() - started_at) * 1000),
                resolve_ms,
                list_ms,
                identity.get("identity_id"),
                identity.get("global_id"),
                matches.get("total", 0),
                len(matches.get("items") or []),
            )
        )
        return {
            "player": resolved.get("player"),
            "identity": identity,
            "sync_status": resolved.get("sync_status"),
            "pagination": {
                "page": matches.get("page", page),
                "page_size": matches.get("page_size", page_size),
                "total": matches.get("total", 0),
                "has_more": matches.get("has_more", False),
            },
            "recent_matches": matches.get("items") or [],
            "cache": {},
        }

    async def enqueue_synced_role(self, *, server: str, name: str) -> dict[str, Any]:
        identity = await self._resolve_synced_identity_only(server=server, name=name)
        if not identity:
            return {
                "error": True,
                "message": "role_identity_not_found",
                "player": {"server": server, "name": _normalize_name(name)},
            }
        sync_repo = self._sync_repo()
        existing_sync_doc = await sync_repo.get_queue_state_by_identity_id(identity.get("_id"))
        if (
            existing_sync_doc
            and str(existing_sync_doc.get("status") or "") == "queued"
            and _coerce_int(existing_sync_doc.get("priority")) == SYNCED_MATCH_PAGE_SYNC_PRIORITY
        ):
            sync_status = await self._serialize_sync_status_with_position(existing_sync_doc)
            return {
                "queued": True,
                "already_queued": True,
                "player": {
                    "server": identity.get("server") or server,
                    "name": _normalize_name(_pick_str(identity.get("name")) or name),
                },
                "identity": self._serialize_identity(identity),
                "sync_status": sync_status,
            }
        sync_doc = await sync_repo.enqueue_existing_identity(
            identity,
            priority=SYNCED_MATCH_PAGE_SYNC_PRIORITY,
            source="synced_match_page",
            mode="incremental_or_full",
        )
        if sync_doc is None:
            sync_doc = existing_sync_doc or await sync_repo.get_queue_state_by_identity_id(identity.get("_id"))
            if not sync_doc or str(sync_doc.get("status") or "") != "syncing":
                return {
                    "error": True,
                    "message": "enqueue_failed",
                    "player": {
                        "server": identity.get("server") or server,
                        "name": _normalize_name(_pick_str(identity.get("name")) or name),
                    },
                    "identity": self._serialize_identity(identity),
                    "sync_status": await self._serialize_sync_status_with_position(sync_doc),
                }
        sync_status = await self._serialize_sync_status_with_position(sync_doc)
        return {
            "queued": bool(sync_doc and sync_doc.get("status") == "queued"),
            "player": {
                "server": identity.get("server") or server,
                "name": _normalize_name(_pick_str(identity.get("name")) or name),
            },
            "identity": self._serialize_identity(identity),
            "sync_status": sync_status,
        }

    async def _fetch_match_replay(self, match_id: int) -> Optional[dict[str, Any]]:
        if self.match_replay_client is None:
            return None
        replay = await self._run_serialized_tuilan_query(
            "match_replay",
            f"match_replay:{match_id}",
            self.match_replay_client.get_match_replay,
            match_id=match_id,
        )
        if not isinstance(replay, dict) or replay.get("error"):
            return None
        return replay

    async def _resolve_global_id_from_match(
        self,
        *,
        match_id: int,
        identity: dict[str, Any],
        server: str,
        name: str,
    ) -> Optional[str]:
        if _pick_str(identity.get("global_id")):
            return _pick_str(identity.get("global_id"))
        replay = await self._fetch_match_replay(match_id)
        if not replay:
            return None
        return extract_global_id_from_match_replay(
            replay,
            role_id=_pick_str(identity.get("role_id"), identity.get("game_role_id")),
            role_name=_normalize_name(name),
            server=server,
        )

    async def _enrich_detail_payload_with_replay(self, payload: dict[str, Any]) -> bool:
        started_at = time.perf_counter()
        match_id = _coerce_int(payload.get("match_id"))
        detail = payload.get("detail")
        if match_id is None or not isinstance(detail, dict):
            return False
        replay = payload.get("replay")
        fetched_replay = False
        if not isinstance(replay, dict) or replay.get("error"):
            replay = await self._fetch_match_replay(match_id)
            fetched_replay = True
            if replay:
                payload["replay"] = replay
        if not replay:
            logger.info(
                "JJC 对局详情 replay 补全完成: match_id={} elapsed_ms={} fetched={} merged={}".format(
                    match_id,
                    int((time.perf_counter() - started_at) * 1000),
                    fetched_replay,
                    False,
                )
            )
            return False
        merge_replay_global_ids_into_match_detail({"data": detail}, replay)
        logger.info(
            "JJC 对局详情 replay 补全完成: match_id={} elapsed_ms={} fetched={} merged={}".format(
                match_id,
                int((time.perf_counter() - started_at) * 1000),
                fetched_replay,
                True,
            )
        )
        return True

    async def _run_serialized_tuilan_query(
        self,
        endpoint_key: str,
        label: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        wait_started_at = time.perf_counter()
        logger.info("等待推栏查询锁: endpoint={} label={}", endpoint_key, label)
        async with self._get_tuilan_query_lock(endpoint_key):
            wait_ms = int((time.perf_counter() - wait_started_at) * 1000)
            query_started_at = time.perf_counter()
            logger.info("获取推栏查询锁: endpoint={} label={} wait_ms={}", endpoint_key, label, wait_ms)
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            finally:
                query_ms = int((time.perf_counter() - query_started_at) * 1000)
                logger.info(
                    "释放推栏查询锁: endpoint={} label={} wait_ms={} query_ms={}",
                    endpoint_key,
                    label,
                    wait_ms,
                    query_ms,
                )

    async def get_role_recent(
        self,
        *,
        server: str,
        name: str,
        identity_hints: Optional[dict[str, Any]] = None,
        cursor: int = 0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        is_first_page = cursor <= 0
        if is_first_page and not force_refresh:
            cached = await self.cache_repo.load_role_recent(
                server,
                name,
                ttl_seconds=self.role_recent_ttl_seconds,
            )
            if cached:
                data = dict(cached.get("data") or {})
                recent_matches = data.get("recent_matches") or []
                missing_match_id_count = sum(
                    1 for item in recent_matches if isinstance(item, dict) and not item.get("match_id")
                )
                logger.info(
                    "JJC 角色近期缓存命中: server={} name={} total_matches={} missing_match_id_count={}",
                    server,
                    name,
                    len(recent_matches),
                    missing_match_id_count,
                )
                await self._hydrate_recent_matches_with_cached_details(recent_matches)
                data["recent_matches"] = recent_matches
                data["cache"] = {
                    "hit": True,
                    "cached_at": cached.get("cached_at"),
                    "ttl_seconds": self.role_recent_ttl_seconds,
                    "force_refresh": False,
                }
                return data

        logger.info(
            "加载 JJC 角色近期数据: server={} name={} hints={} cursor={} force_refresh={}",
            server,
            name,
            identity_hints or {},
            cursor,
            force_refresh,
        )
        identity = await self._resolve_role_identity(server=server, name=name, identity_hints=identity_hints or {})
        if identity.get("error"):
            return identity

        payload = await self._build_role_recent_payload(server=server, name=name, identity=identity, cursor=cursor)
        if payload.get("error"):
            return payload
        if is_first_page:
            cached_at = time.time()
            await self.cache_repo.save_role_recent(server, name, {"cached_at": cached_at, "data": copy.deepcopy(payload)})
            await self._hydrate_recent_matches_with_cached_details(
                payload.get("recent_matches") or []
            )
            payload["cache"] = {
                "hit": False,
                "cached_at": cached_at,
                "ttl_seconds": self.role_recent_ttl_seconds,
                "force_refresh": bool(force_refresh),
            }
        else:
            await self._hydrate_recent_matches_with_cached_details(
                payload.get("recent_matches") or []
            )
            payload["cache"] = {"hit": False, "cached_at": time.time(), "force_refresh": bool(force_refresh)}
        return payload

    async def get_role_indicator(
        self,
        *,
        server: str,
        name: str,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        global_id: Optional[str] = None,
        role_id: Optional[str] = None,
        zone: Optional[str] = None,
        force_refresh: bool = False,
        identity_only: bool = False,
    ) -> dict[str, Any]:
        if identity_only:
            raw_identity = await self._resolve_synced_identity_only(server=server, name=name)
            if not raw_identity:
                return {
                    "error": True,
                    "message": "role_identity_not_found",
                    "player": {"server": server, "name": _normalize_name(name)},
                }
            identity = self._serialize_identity(raw_identity)
            if game_role_id and not identity.get("game_role_id"):
                identity["game_role_id"] = game_role_id
            if global_role_id and not identity.get("global_role_id"):
                identity["global_role_id"] = global_role_id
            if global_id and not identity.get("global_id"):
                identity["global_id"] = global_id
            if role_id and not identity.get("role_id"):
                identity["role_id"] = role_id
            if zone and not identity.get("zone"):
                identity["zone"] = zone
        else:
            identity = await self._resolve_role_identity(
                server=server,
                name=name,
                identity_hints={
                    "game_role_id": game_role_id or None,
                    "global_role_id": global_role_id or None,
                    "global_id": global_id or None,
                    "role_id": role_id or None,
                    "zone": zone or None,
                },
            )
            if identity.get("error"):
                return identity

        identity_key = identity.get("identity_key") or ""
        if not identity_key:
            return {"error": True, "message": "identity_key_missing", "identity": identity}

        cached = None
        if not force_refresh:
            cached = await self.cache_repo.load_role_indicator(
                identity_key,
                ttl_seconds=self.role_indicator_ttl_seconds,
            )
        if cached:
            logger.info(
                "JJC 角色 indicator 缓存命中: server={} name={} identity_key={}",
                server,
                name,
                identity_key,
            )
            return {
                "player": {"server": server, "name": _normalize_name(name)},
                "identity": identity,
                "indicator": cached.get("indicator") or {},
                "raw": cached.get("raw") or {},
                "cache": {
                    "hit": True,
                    "cached_at": cached.get("cached_at"),
                    "ttl_seconds": self.role_indicator_ttl_seconds,
                },
            }

        resolved_game_role_id = _pick_str(identity.get("game_role_id"))
        resolved_zone = _pick_str(identity.get("zone"))
        if not resolved_game_role_id or not resolved_zone:
            return {"error": True, "message": "indicator_params_missing", "identity": identity}

        logger.info(
            "JJC 角色 indicator 实时请求: server={} name={} game_role_id={} zone={}",
            server,
            name,
            resolved_game_role_id,
            resolved_zone,
        )
        raw = await self._run_serialized_tuilan_query(
            "role_indicator",
            f"role_indicator:{server}:{name}",
            self.role_indicator_fetcher,
            resolved_game_role_id,
            resolved_zone,
            server,
            tuilan_request=self.tuilan_request,
            rank=None,
            name=name,
        )
        if not isinstance(raw, dict):
            return {"error": True, "message": "indicator_unavailable", "identity": identity}
        if raw.get("error"):
            return {"error": True, "message": "indicator_unavailable", "identity": identity}

        parsed = _parse_3v3_indicator(raw)
        if parsed.get("error"):
            return {
                "error": True,
                "message": parsed.get("error") or "indicator_parse_failed",
                "identity": identity,
                "raw": raw,
            }

        person_id = _extract_person_id_from_indicator(raw)
        raw_role_info = (raw.get("data") or {}).get("role_info") if isinstance(raw.get("data"), dict) else None
        if not isinstance(raw_role_info, dict):
            raw_role_info = {}
        indicator_global_role_id = _pick_str(
            raw_role_info.get("global_role_id"),
            raw_role_info.get("globalRoleId"),
            identity.get("global_role_id"),
        )
        indicator_role_id = _pick_str(
            raw_role_info.get("role_id"),
            raw_role_info.get("roleId"),
            identity.get("role_id"),
            resolved_game_role_id,
        )
        if indicator_global_role_id:
            try:
                updated_identity = await _maybe_await(
                    self.kungfu_cache_repo.upsert_role_identity_from_indicator(
                        server=server,
                        name=name,
                        zone=resolved_zone,
                        game_role_id=resolved_game_role_id,
                        global_role_id=indicator_global_role_id,
                        role_id=indicator_role_id,
                        person_id=person_id,
                        global_id=_pick_str(identity.get("global_id")),
                    )
                )
                if isinstance(updated_identity, dict):
                    identity = updated_identity
                    identity_key = _pick_str(updated_identity.get("identity_key")) or identity_key
            except Exception as exc:
                logger.warning(f"JJC 角色 indicator: 写入 role_identities 失败 server={server} name={name} error={exc}")

        cached_at = time.time()
        cache_payload = {
            "identity_key": identity_key,
            "server": server,
            "name": _normalize_name(name),
            "game_role_id": resolved_game_role_id,
            "global_role_id": indicator_global_role_id or _pick_str(identity.get("global_role_id")),
            "global_id": _pick_str(identity.get("global_id")),
            "role_id": indicator_role_id or _pick_str(identity.get("role_id")),
            "person_id": person_id,
            "zone": resolved_zone,
            "indicator": parsed,
            "raw": raw,
            "cached_at": cached_at,
        }
        await self.cache_repo.save_role_indicator(identity_key, cache_payload)

        return {
            "player": {"server": server, "name": _normalize_name(name)},
            "identity": identity,
            "indicator": parsed,
            "raw": raw,
            "cache": {
                "hit": False,
                "cached_at": cached_at,
                "ttl_seconds": self.role_indicator_ttl_seconds,
                "force_refresh": bool(force_refresh),
            },
        }

    async def _resolve_role_identity(
        self,
        *,
        server: str,
        name: str,
        identity_hints: dict[str, Any],
    ) -> dict[str, Any]:
        """按优先级解析角色身份：role_identities → role_jjc_cache → live ranking。"""
        display_name = _normalize_name(name)
        hint_global_id = _pick_str(identity_hints.get("global_id"))
        hint_global_role_id = _pick_str(identity_hints.get("global_role_id"))
        hint_role_id = _pick_str(identity_hints.get("role_id"))
        hint_game_role_id = _pick_str(identity_hints.get("game_role_id"))
        hint_zone = _pick_str(identity_hints.get("zone"))

        # ---- 1. 前端直接传入 global_role_id ----
        if hint_global_role_id:
            logger.info("JJC 角色标识解析: 直接使用前端传入 global_role_id server={} name={}", server, name)
            identity_key = f"global_id:{hint_global_id}" if hint_global_id else f"global:{hint_global_role_id}"
            return {
                "server": server,
                "name": display_name,
                "global_role_id": hint_global_role_id,
                "global_id": hint_global_id,
                "role_id": hint_role_id,
                "game_role_id": hint_game_role_id or hint_role_id,
                "zone": hint_zone,
                "source": "detail_hint_global_role_id",
                "identity_key": identity_key,
            }

        # ---- 2. 有 game_role_id + zone → 先查 role_identities，再走 indicator 补 global ----
        if hint_game_role_id and hint_zone:
            identity = await self.kungfu_cache_repo.resolve_role_identity(
                server=server,
                name=name,
                zone=hint_zone,
                game_role_id=hint_game_role_id,
                global_id=hint_global_id,
            )
            if identity:
                gid = _pick_str(identity.get("global_role_id"))
                if gid:
                    logger.info("JJC 角色标识解析: 使用 role_identities (hints) server={} name={}", server, name)
                    return {
                        "server": server,
                        "name": display_name,
                        "global_role_id": gid,
                        "global_id": _pick_str(identity.get("global_id")) or hint_global_id,
                        "role_id": _pick_str(identity.get("role_id")) or hint_role_id,
                        "game_role_id": _pick_str(identity.get("game_role_id")) or hint_game_role_id,
                        "zone": _pick_str(identity.get("zone")) or hint_zone,
                        "source": "role_identity_hint_match",
                        "identity_key": identity.get("identity_key") or f"global:{gid}",
                    }
            identity = await self._resolve_identity_from_indicator(
                server=server,
                name=name,
                game_role_id=hint_game_role_id,
                zone=hint_zone,
                role_id=hint_role_id,
                global_id=hint_global_id,
                source="detail_hint_game_role_id",
            )
            if identity:
                return identity

        # ---- 3. 查 role_identities 按 server + name ----
        identity = await self.kungfu_cache_repo.resolve_role_identity(
            server=server,
            name=name,
            global_id=hint_global_id,
        )
        if identity:
            gid = _pick_str(identity.get("global_role_id"))
            if gid:
                logger.info("JJC 角色标识解析: 使用 role_identities (name) server={} name={}", server, name)
                return {
                    "server": server,
                    "name": display_name,
                    "global_role_id": gid,
                    "global_id": _pick_str(identity.get("global_id")) or hint_global_id,
                    "role_id": _pick_str(identity.get("role_id")),
                    "game_role_id": _pick_str(identity.get("game_role_id")),
                    "zone": _pick_str(identity.get("zone")),
                    "source": "role_identity_name_match",
                    "identity_key": identity.get("identity_key") or f"global:{gid}",
                }
            z = _pick_str(identity.get("zone"))
            grid = _pick_str(identity.get("game_role_id"))
            if z and grid:
                identity_result = await self._resolve_identity_from_indicator(
                    server=server,
                    name=name,
                    game_role_id=grid,
                    zone=z,
                    role_id=_pick_str(identity.get("role_id")),
                    global_id=_pick_str(identity.get("global_id")) or hint_global_id,
                    source="role_identity_indicator",
                )
                if identity_result:
                    return identity_result

        # ---- 4. 查新缓存 role_jjc_cache 中的身份字段 ----
        jjc_cache = await self.kungfu_cache_repo.load_new_kungfu_cache_raw(
            server=server,
            name=name,
        )
        if jjc_cache:
            cache_global_role_id = _pick_str(jjc_cache.get("global_role_id"))
            cache_global_id = _pick_str(jjc_cache.get("global_id")) or hint_global_id
            cache_game_role_id = _pick_str(jjc_cache.get("game_role_id"))
            cache_zone = _pick_str(jjc_cache.get("zone"))
            cache_role_id = _pick_str(jjc_cache.get("role_id"))
            if cache_global_role_id:
                logger.info("JJC 角色标识解析: 使用新缓存 global_role_id server={} name={}", server, name)
                return {
                    "server": server,
                    "name": display_name,
                    "global_role_id": cache_global_role_id,
                    "global_id": cache_global_id,
                    "role_id": cache_role_id,
                    "game_role_id": cache_game_role_id or cache_role_id,
                    "zone": cache_zone,
                    "source": "new_cache_global_role_id",
                    "identity_key": jjc_cache.get("identity_key") or f"global:{cache_global_role_id}",
                }
            if cache_game_role_id and cache_zone:
                identity = await self._resolve_identity_from_indicator(
                    server=server,
                    name=name,
                    game_role_id=cache_game_role_id,
                    zone=cache_zone,
                    role_id=cache_role_id,
                    global_id=cache_global_id,
                    source="new_cache_game_role_id",
                )
                if identity:
                    return identity

        # ---- 5. 实时排行榜查询 ----
        logger.info("等待推栏查询锁: endpoint=live_ranking label=live_ranking:{}:{}", server, name)
        async with self._get_tuilan_query_lock("live_ranking"):
            logger.info("获取推栏查询锁: endpoint=live_ranking label=live_ranking:{}:{}", server, name)
            try:
                ranking_result = await self.ranking_service.query_jjc_ranking()
            finally:
                logger.info("释放推栏查询锁: endpoint=live_ranking label=live_ranking:{}:{}", server, name)
        if not ranking_result.get("error") and ranking_result.get("code") == 0:
            for player in ranking_result.get("data", []):
                if not isinstance(player, dict):
                    continue
                person_info = player.get("personInfo", {}) or {}
                player_server = _pick_str(person_info.get("server"))
                player_name = _normalize_name(_pick_str(person_info.get("roleName")))
                if player_server != server or player_name != display_name:
                    continue
                ranking_global_role_id = _pick_str(person_info.get("globalRoleId"))
                ranking_game_role_id = _pick_str(person_info.get("gameRoleId"))
                ranking_zone = _pick_str(person_info.get("zone"))
                if ranking_global_role_id:
                    logger.info("JJC 角色标识解析: 使用实时榜单 global_role_id server={} name={}", server, name)
                    return {
                        "server": server,
                        "name": display_name,
                        "global_role_id": ranking_global_role_id,
                        "role_id": ranking_game_role_id,
                        "game_role_id": ranking_game_role_id,
                        "zone": ranking_zone,
                        "source": "live_ranking_global_role_id",
                        "identity_key": f"global:{ranking_global_role_id}",
                    }
                if ranking_game_role_id and ranking_zone:
                    identity = await self._resolve_identity_from_indicator(
                        server=server,
                        name=name,
                        game_role_id=ranking_game_role_id,
                        zone=ranking_zone,
                        role_id=ranking_game_role_id,
                        global_id=None,
                        source="live_ranking_game_role_id",
                    )
                    if identity:
                        return identity

        logger.warning("JJC 角色标识解析失败: server={} name={} hints={}", server, name, identity_hints)
        return {"error": True, "message": "role_identity_not_found", "server": server, "name": display_name}

    async def _resolve_identity_from_indicator(
        self,
        *,
        server: str,
        name: str,
        game_role_id: str,
        zone: str,
        role_id: Optional[str],
        global_id: Optional[str],
        source: str,
    ) -> Optional[dict[str, Any]]:
        logger.info(
            "JJC 角色标识解析: 调用 indicator 补全标识 server={} name={} game_role_id={} zone={} source={}",
            server,
            name,
            game_role_id,
            zone,
            source,
        )
        result = await self._run_serialized_tuilan_query(
            "role_indicator",
            f"role_indicator:{server}:{name}",
            self.role_indicator_fetcher,
            game_role_id,
            zone,
            server,
            tuilan_request=self.tuilan_request,
            rank=None,
            name=name,
        )
        if not isinstance(result, dict):
            return None
        role_info = (result.get("data") or {}).get("role_info") or {}
        global_role_id = _pick_str(role_info.get("global_role_id"), role_info.get("globalRoleId"))
        resolved_role_id = _pick_str(role_info.get("role_id"), role_info.get("roleId"), role_id, game_role_id)
        person_id = _extract_person_id_from_indicator(result)
        if not global_role_id:
            logger.warning(
                "JJC 角色标识解析: indicator 未返回 global_role_id server={} name={} source={}",
                server,
                name,
                source,
            )
            return None
        try:
            await _maybe_await(
                self.kungfu_cache_repo.upsert_role_identity_from_indicator(
                    server=server,
                    name=name,
                    zone=zone,
                    game_role_id=game_role_id,
                    global_role_id=global_role_id,
                    role_id=resolved_role_id,
                    person_id=person_id,
                    global_id=global_id,
                )
            )
        except Exception as exc:
            logger.warning(f"JJC 角色标识解析: 写入 role_identities 失败 server={server} name={name} error={exc}")
        return {
            "server": server,
            "name": _normalize_name(name),
            "global_role_id": global_role_id,
            "global_id": global_id,
            "role_id": resolved_role_id,
            "person_id": person_id,
            "game_role_id": game_role_id,
            "zone": zone,
            "source": source,
            "identity_key": f"global_id:{global_id}" if global_id else f"global:{global_role_id}",
        }

    async def _build_role_recent_payload(self, *, server: str, name: str, identity: dict[str, Any], cursor: int = 0) -> dict[str, Any]:
        global_role_id = _pick_str(identity.get("global_role_id"))
        if not global_role_id:
            return {"error": True, "message": "global_role_id_missing", "identity": identity}

        raw = await self._run_serialized_tuilan_query(
            "match_history",
            f"match_history:{server}:{name}",
            self.match_history_client.get_mine_match_history,
            global_role_id=global_role_id,
            size=self.max_recent_matches,
            cursor=cursor,
        )
        if not isinstance(raw, dict):
            return {"error": True, "message": "invalid_response", "identity": identity}
        if raw.get("error"):
            return {"error": True, "message": raw.get("error"), "identity": identity}
        if raw.get("code") != 0 or raw.get("msg") != "success":
            return {"error": True, "message": raw.get("msg") or "unknown_error", "identity": identity, "raw": raw}

        history = raw.get("data") or []
        first_raw_match = next((item for item in history if isinstance(item, dict)), None)
        recent_matches = normalize_recent_matches(
            history,
            kungfu_pinyin_to_chinese=self.kungfu_pinyin_to_chinese,
            max_recent_matches=self.max_recent_matches,
        )
        missing_match_id_count = sum(1 for item in recent_matches if not item.get("match_id"))
        missing_avg_grade_count = sum(1 for item in recent_matches if item.get("avg_grade") is None)
        if not _pick_str(identity.get("global_id")):
            first_match_id = next(
                (
                    _coerce_int(item.get("match_id"))
                    for item in recent_matches
                    if isinstance(item, dict) and _coerce_int(item.get("match_id")) is not None
                ),
                None,
            )
            if first_match_id is not None:
                global_id = await self._resolve_global_id_from_match(
                    match_id=first_match_id,
                    identity=identity,
                    server=server,
                    name=name,
                )
                if global_id:
                    identity = dict(identity)
                    identity["global_id"] = global_id
                    identity["identity_hints"] = {
                        **(identity.get("identity_hints") or {}),
                        "global_id": global_id,
                        "source_match_id": first_match_id,
                    }

        logger.info(
            "JJC 角色近期构建完成: server={} name={} history_total={} recent_total={} missing_match_id_count={} missing_avg_grade_count={} identity_source={}",
            server,
            name,
            sum(1 for item in history if isinstance(item, dict)),
            len(recent_matches),
            missing_match_id_count,
            missing_avg_grade_count,
            identity.get("source"),
        )
        if recent_matches:
            logger.info(
                "JJC 推栏战局历史样本字段: server={} name={} first_keys={} first_id_like_fields={} first_grade_like_fields={}",
                server,
                name,
                sorted(first_raw_match.keys()) if isinstance(first_raw_match, dict) else [],
                _extract_id_like_fields(first_raw_match) if isinstance(first_raw_match, dict) else {},
                _extract_grade_like_fields(first_raw_match) if isinstance(first_raw_match, dict) else {},
            )
        if missing_avg_grade_count > 0:
            missing_avg_grade_samples = []
            for item in raw.get("data") or []:
                if not isinstance(item, dict):
                    continue
                parsed_avg_grade = _extract_avg_grade(item)
                if parsed_avg_grade is not None:
                    continue
                missing_avg_grade_samples.append(
                    {
                        "keys": sorted(item.keys()),
                        "grade_like_fields": _extract_grade_like_fields(item),
                        "time": item.get("match_time") or item.get("startTime") or item.get("start_time"),
                        "kungfu": item.get("kungfu") or item.get("kungfu_name"),
                        "won": item.get("won"),
                    }
                )
                if len(missing_avg_grade_samples) >= 3:
                    break
            logger.warning(
                "JJC 角色近期存在缺失段位字段样本: server={} name={} samples={}",
                server,
                name,
                missing_avg_grade_samples,
            )
        if missing_match_id_count > 0:
            missing_match_id_samples = []
            for item in raw.get("data") or []:
                if not isinstance(item, dict):
                    continue
                if _extract_match_id(item) is not None:
                    continue
                missing_match_id_samples.append(
                    {
                        "keys": sorted(item.keys()),
                        "id_like_fields": _extract_id_like_fields(item),
                        "time": item.get("match_time") or item.get("startTime") or item.get("start_time"),
                        "kungfu": item.get("kungfu") or item.get("kungfu_name"),
                        "won": item.get("won"),
                    }
                )
                if len(missing_match_id_samples) >= 3:
                    break
            logger.warning(
                "JJC 角色近期存在缺失对局ID样本: server={} name={} samples={}",
                server,
                name,
                missing_match_id_samples,
            )

        total_returned = len(history)
        has_more = total_returned >= self.max_recent_matches
        next_cursor = cursor + total_returned if has_more else None

        return {
            "player": {"server": server, "name": name},
            "identity": identity,
            "identity_key": identity.get("identity_key"),
            "pagination": {
                "cursor": cursor,
                "has_more": has_more,
                "next_cursor": next_cursor,
            },
            "recent_matches": recent_matches,
        }

    async def _hydrate_recent_matches_with_cached_details(
        self,
        recent_matches: list,
    ) -> None:
        if not recent_matches:
            return
        match_ids = []
        for item in recent_matches:
            if not isinstance(item, dict):
                continue
            mid = _coerce_int(item.get("match_id"))
            if mid:
                match_ids.append(mid)
        if not match_ids:
            for item in recent_matches:
                if isinstance(item, dict):
                    item.pop("cached_detail_summary", None)
            return
        summaries = await self.cache_repo.batch_load_cached_detail_summaries(match_ids)
        for item in recent_matches:
            if not isinstance(item, dict):
                continue
            mid = _coerce_int(item.get("match_id"))
            if mid is not None and mid in summaries:
                item["cached_detail_summary"] = summaries[mid]
            else:
                item.pop("cached_detail_summary", None)

    async def get_match_detail(self, *, match_id: Union[int, str]) -> dict[str, Any]:
        started_at = time.perf_counter()
        normalized_match_id = _coerce_int(match_id)
        if normalized_match_id is None:
            return {"error": True, "message": "invalid_match_id"}

        phase_started_at = time.perf_counter()
        cached = await self.cache_repo.load_match_detail(normalized_match_id)
        cache_ms = int((time.perf_counter() - phase_started_at) * 1000)
        if cached:
            data = dict(cached.get("data") or {})
            before = repr(data)
            phase_started_at = time.perf_counter()
            await self._enrich_detail_payload_with_replay(data)
            enrich_ms = int((time.perf_counter() - phase_started_at) * 1000)
            if repr(data) != before:
                phase_started_at = time.perf_counter()
                await self.cache_repo.save_match_detail(
                    normalized_match_id,
                    {"cached_at": cached.get("cached_at") or time.time(), "data": data},
                )
                save_ms = int((time.perf_counter() - phase_started_at) * 1000)
                phase_started_at = time.perf_counter()
                await self._project_match_detail_payload(
                    match_id=normalized_match_id,
                    payload=data,
                    source="inspect_cache_hit_replay_enrich",
                )
                project_identity_ms = int((time.perf_counter() - phase_started_at) * 1000)
                phase_started_at = time.perf_counter()
                await self._project_match_detail_participants(
                    match_id=normalized_match_id,
                    payload={"cached_at": cached.get("cached_at") or time.time(), "data": data},
                    detail_source="ranking_detail",
                )
                project_participants_ms = int((time.perf_counter() - phase_started_at) * 1000)
            else:
                save_ms = 0
                project_identity_ms = 0
                project_participants_ms = 0
            data["cache"] = {"hit": True, "cached_at": cached.get("cached_at")}
            logger.info(
                "JJC 对局详情查询完成: match_id={} cache_hit=True elapsed_ms={} cache_ms={} "
                "enrich_ms={} save_ms={} project_identity_ms={} project_participants_ms={}".format(
                    normalized_match_id,
                    int((time.perf_counter() - started_at) * 1000),
                    cache_ms,
                    enrich_ms,
                    save_ms,
                    project_identity_ms,
                    project_participants_ms,
                )
            )
            return data

        logger.info("加载 JJC 对局详情: match_id={} cache_ms={}", normalized_match_id, cache_ms)
        phase_started_at = time.perf_counter()
        detail = await self._run_serialized_tuilan_query(
            "match_detail",
            f"match_detail:{normalized_match_id}",
            self.match_detail_client.get_match_detail_obj,
            match_id=normalized_match_id,
        )
        detail_ms = int((time.perf_counter() - phase_started_at) * 1000)
        if not isinstance(detail, MatchDetailResponse):
            logger.info(
                "JJC 对局详情查询完成: match_id={} cache_hit=False elapsed_ms={} cache_ms={} detail_ms={} error=invalid_response".format(
                    normalized_match_id,
                    int((time.perf_counter() - started_at) * 1000),
                    cache_ms,
                    detail_ms,
                )
            )
            return {"error": True, "message": "invalid_response"}
        if detail.code == -1 and detail.msg.strip() == "no data found" and detail.data is None:
            payload: dict[str, Any] = {
                "match_id": normalized_match_id,
                "unavailable": True,
                "code": -1,
                "message": "no data found",
                "detail": None,
            }
            cached_at = time.time()
            phase_started_at = time.perf_counter()
            await self.cache_repo.save_match_detail(normalized_match_id, {"cached_at": cached_at, "data": payload})
            save_ms = int((time.perf_counter() - phase_started_at) * 1000)
            phase_started_at = time.perf_counter()
            await self._clear_match_detail_participants(
                match_id=normalized_match_id,
                source="inspect_cache_miss_unavailable",
            )
            clear_participants_ms = int((time.perf_counter() - phase_started_at) * 1000)
            payload["cache"] = {"hit": False, "cached_at": cached_at}
            logger.info(
                "JJC 对局详情查询完成: match_id={} cache_hit=False unavailable=True elapsed_ms={} "
                "cache_ms={} detail_ms={} save_ms={} clear_participants_ms={}".format(
                    normalized_match_id,
                    int((time.perf_counter() - started_at) * 1000),
                    cache_ms,
                    detail_ms,
                    save_ms,
                    clear_participants_ms,
                )
            )
            return payload
        if detail.code != 0 or not detail.data:
            logger.info(
                "JJC 对局详情查询完成: match_id={} cache_hit=False elapsed_ms={} cache_ms={} detail_ms={} "
                "code={} error={}".format(
                    normalized_match_id,
                    int((time.perf_counter() - started_at) * 1000),
                    cache_ms,
                    detail_ms,
                    detail.code,
                    detail.msg or "unknown_error",
                )
            )
            return {"error": True, "message": detail.msg or "unknown_error", "code": detail.code}

        payload = {
            "match_id": normalized_match_id,
            "detail": asdict(detail.data),
        }
        for team_key in ("team1", "team2"):
            team = payload["detail"].get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info") or []
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue
                player["kungfu"] = self._translate_kungfu_name(player.get("kungfu"))
        phase_started_at = time.perf_counter()
        await self._enrich_detail_payload_with_replay(payload)
        enrich_ms = int((time.perf_counter() - phase_started_at) * 1000)
        cached_at = time.time()
        phase_started_at = time.perf_counter()
        await self.cache_repo.save_match_detail(normalized_match_id, {"cached_at": cached_at, "data": payload})
        save_ms = int((time.perf_counter() - phase_started_at) * 1000)
        phase_started_at = time.perf_counter()
        await self._project_match_detail_payload(
            match_id=normalized_match_id,
            payload=payload,
            source="inspect_cache_miss",
        )
        project_identity_ms = int((time.perf_counter() - phase_started_at) * 1000)
        phase_started_at = time.perf_counter()
        await self._project_match_detail_participants(
            match_id=normalized_match_id,
            payload={"cached_at": cached_at, "data": payload},
            detail_source="ranking_detail",
        )
        project_participants_ms = int((time.perf_counter() - phase_started_at) * 1000)
        payload["cache"] = {"hit": False, "cached_at": cached_at}
        logger.info(
            "JJC 对局详情查询完成: match_id={} cache_hit=False elapsed_ms={} cache_ms={} detail_ms={} "
            "enrich_ms={} save_ms={} project_identity_ms={} project_participants_ms={}".format(
                normalized_match_id,
                int((time.perf_counter() - started_at) * 1000),
                cache_ms,
                detail_ms,
                enrich_ms,
                save_ms,
                project_identity_ms,
                project_participants_ms,
            )
        )
        return payload

    async def _project_match_detail_payload(
        self,
        *,
        match_id: int,
        payload: dict[str, Any],
        source: str,
    ) -> None:
        if self.match_detail_projection_service is None:
            return
        try:
            await self.match_detail_projection_service.project_payload(
                match_id=match_id,
                payload=payload,
                source=source,
            )
        except Exception as exc:
            logger.warning(
                "JJC 对局详情身份投影失败: match_id=%s source=%s error=%s",
                match_id,
                source,
                exc,
            )
            payload["projection_error"] = True
            payload["projection_message"] = str(exc) or exc.__class__.__name__

    async def _project_match_detail_participants(
        self,
        *,
        match_id: int,
        payload: dict[str, Any],
        detail_source: str,
    ) -> None:
        service = self.match_detail_participant_projection_service
        if service is None:
            return
        try:
            await service.project_payload(
                match_id=match_id,
                payload=payload,
                source=detail_source,
            )
        except Exception as exc:
            logger.warning(
                "JJC 对局详情参与者投影失败: match_id=%s source=%s error=%s",
                match_id,
                detail_source,
                exc,
            )

    async def _clear_match_detail_participants(
        self,
        *,
        match_id: int,
        source: str,
    ) -> None:
        service = self.match_detail_participant_projection_service
        if service is None:
            return
        try:
            await service.clear_match(match_id)
        except Exception as exc:
            logger.warning(
                "JJC 对局详情参与者投影清理失败: match_id=%s source=%s error=%s",
                match_id,
                source,
                exc,
            )
