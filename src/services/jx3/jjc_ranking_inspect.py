from __future__ import annotations

import asyncio
import threading
import time
from weakref import WeakKeyDictionary
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional, Union

from nonebot import logger

from src.services.jx3.jjc_cache_repo import JjcCacheRepo
from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.match_history import MatchHistoryClient
from src.services.jx3.match_detail import MatchDetailClient, MatchDetailResponse
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo


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
    role_recent_ttl_seconds: int = 600
    max_recent_matches: int = 20
    _tuilan_query_locks: WeakKeyDictionary = field(default_factory=WeakKeyDictionary, init=False, repr=False)
    _tuilan_query_locks_guard: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _get_tuilan_query_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._tuilan_query_locks_guard:
            lock = self._tuilan_query_locks.get(loop)
            if lock is None:
                lock = asyncio.Lock()
                self._tuilan_query_locks[loop] = lock
        return lock

    def _translate_kungfu_name(self, value: Any) -> str:
        text = _pick_str(value) or ""
        if not text:
            return ""
        return self.kungfu_pinyin_to_chinese.get(text, text)

    async def _run_serialized_tuilan_query(
        self,
        label: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        logger.info("等待推栏查询锁: label={}", label)
        async with self._get_tuilan_query_lock():
            logger.info("获取推栏查询锁: label={}", label)
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            finally:
                logger.info("释放推栏查询锁: label={}", label)

    async def get_role_recent(
        self,
        *,
        server: str,
        name: str,
        identity_hints: Optional[dict[str, Any]] = None,
        cursor: int = 0,
    ) -> dict[str, Any]:
        is_first_page = cursor <= 0
        if is_first_page:
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
                data["cache"] = {"hit": True, "cached_at": cached.get("cached_at"), "ttl_seconds": self.role_recent_ttl_seconds}
                return data

        logger.info("加载 JJC 角色近期数据: server={} name={} hints={} cursor={}", server, name, identity_hints or {}, cursor)
        identity = await self._resolve_role_identity(server=server, name=name, identity_hints=identity_hints or {})
        if identity.get("error"):
            return identity

        payload = await self._build_role_recent_payload(server=server, name=name, identity=identity, cursor=cursor)
        if payload.get("error"):
            return payload
        if is_first_page:
            cached_at = time.time()
            await self.cache_repo.save_role_recent(server, name, {"cached_at": cached_at, "data": payload})
            payload["cache"] = {"hit": False, "cached_at": cached_at, "ttl_seconds": self.role_recent_ttl_seconds}
        else:
            payload["cache"] = {"hit": False, "cached_at": time.time()}
        return payload

    async def _resolve_role_identity(
        self,
        *,
        server: str,
        name: str,
        identity_hints: dict[str, Any],
    ) -> dict[str, Any]:
        """按优先级解析角色身份：role_identities → role_jjc_cache → live ranking → 旧 kungfu_cache。"""
        display_name = _normalize_name(name)
        hint_global_role_id = _pick_str(identity_hints.get("global_role_id"))
        hint_role_id = _pick_str(identity_hints.get("role_id"))
        hint_game_role_id = _pick_str(identity_hints.get("game_role_id"))
        hint_zone = _pick_str(identity_hints.get("zone"))

        # ---- 1. 前端直接传入 global_role_id ----
        if hint_global_role_id:
            logger.info("JJC 角色标识解析: 直接使用前端传入 global_role_id server={} name={}", server, name)
            return {
                "server": server,
                "name": display_name,
                "global_role_id": hint_global_role_id,
                "role_id": hint_role_id,
                "game_role_id": hint_game_role_id or hint_role_id,
                "zone": hint_zone,
                "source": "detail_hint_global_role_id",
                "identity_key": f"global:{hint_global_role_id}",
            }

        # ---- 2. 有 game_role_id + zone → 先查 role_identities，再走 indicator 补 global ----
        if hint_game_role_id and hint_zone:
            identity = await self.kungfu_cache_repo.resolve_role_identity(
                server=server,
                name=name,
                zone=hint_zone,
                game_role_id=hint_game_role_id,
            )
            if identity:
                gid = _pick_str(identity.get("global_role_id"))
                if gid:
                    logger.info("JJC 角色标识解析: 使用 role_identities (hints) server={} name={}", server, name)
                    return {
                        "server": server,
                        "name": display_name,
                        "global_role_id": gid,
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
                source="detail_hint_game_role_id",
            )
            if identity:
                return identity

        # ---- 3. 查 role_identities 按 server + name ----
        identity = await self.kungfu_cache_repo.resolve_role_identity(
            server=server,
            name=name,
        )
        if identity:
            gid = _pick_str(identity.get("global_role_id"))
            if gid:
                logger.info("JJC 角色标识解析: 使用 role_identities (name) server={} name={}", server, name)
                return {
                    "server": server,
                    "name": display_name,
                    "global_role_id": gid,
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
            cache_game_role_id = _pick_str(jjc_cache.get("game_role_id"))
            cache_zone = _pick_str(jjc_cache.get("zone"))
            cache_role_id = _pick_str(jjc_cache.get("role_id"))
            if cache_global_role_id:
                logger.info("JJC 角色标识解析: 使用新缓存 global_role_id server={} name={}", server, name)
                return {
                    "server": server,
                    "name": display_name,
                    "global_role_id": cache_global_role_id,
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
                    source="new_cache_game_role_id",
                )
                if identity:
                    return identity

        # ---- 5. 实时排行榜查询 ----
        logger.info("等待推栏查询锁: label=live_ranking:{}:{}", server, name)
        async with self._get_tuilan_query_lock():
            logger.info("获取推栏查询锁: label=live_ranking:{}:{}", server, name)
            try:
                ranking_result = await self.ranking_service.query_jjc_ranking()
            finally:
                logger.info("释放推栏查询锁: label=live_ranking:{}:{}", server, name)
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
                        source="live_ranking_game_role_id",
                    )
                    if identity:
                        return identity

        # ---- 6. 最后回退旧 kungfu_cache ----
        old_doc = await self.kungfu_cache_repo.load_legacy_kungfu_cache_raw(server, name)
        if old_doc:
            cache_global_role_id = _pick_str(old_doc.get("global_role_id"))
            cache_role_id = _pick_str(old_doc.get("role_id"))
            cache_zone = _pick_str(old_doc.get("zone"))
            if cache_global_role_id:
                logger.info("JJC 角色标识解析: 使用旧缓存 global_role_id server={} name={}", server, name)
                return {
                    "server": server,
                    "name": display_name,
                    "global_role_id": cache_global_role_id,
                    "role_id": cache_role_id,
                    "game_role_id": cache_role_id,
                    "zone": cache_zone,
                    "source": "kungfu_cache_global_role_id",
                    "identity_key": f"global:{cache_global_role_id}",
                }
            if cache_role_id and cache_zone:
                identity = await self._resolve_identity_from_indicator(
                    server=server,
                    name=name,
                    game_role_id=cache_role_id,
                    zone=cache_zone,
                    role_id=cache_role_id,
                    source="kungfu_cache_role_id",
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
        if not global_role_id:
            logger.warning(
                "JJC 角色标识解析: indicator 未返回 global_role_id server={} name={} source={}",
                server,
                name,
                source,
            )
            return None
        try:
            await self.kungfu_cache_repo.upsert_role_identity_from_indicator(
                server=server,
                name=name,
                zone=zone,
                game_role_id=game_role_id,
                global_role_id=global_role_id,
                role_id=resolved_role_id,
            )
        except Exception as exc:
            logger.warning("JJC 角色标识解析: 写入 role_identities 失败 server={} name={} error={}", server, name, exc)
        return {
            "server": server,
            "name": _normalize_name(name),
            "global_role_id": global_role_id,
            "role_id": resolved_role_id,
            "game_role_id": game_role_id,
            "zone": zone,
            "source": source,
            "identity_key": f"global:{global_role_id}",
        }

    async def _build_role_recent_payload(self, *, server: str, name: str, identity: dict[str, Any], cursor: int = 0) -> dict[str, Any]:
        global_role_id = _pick_str(identity.get("global_role_id"))
        if not global_role_id:
            return {"error": True, "message": "global_role_id_missing", "identity": identity}

        raw = await self._run_serialized_tuilan_query(
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
        history_3v3 = []
        first_raw_match = next((item for item in history if isinstance(item, dict)), None)
        for item in history:
            if not isinstance(item, dict):
                continue
            pvp_type = _coerce_int(item.get("pvpType") or item.get("pvp_type") or item.get("type"))
            if pvp_type is not None and pvp_type != 3:
                continue
            match_id = _extract_match_id(item)
            match_time = _extract_match_time(item)
            history_3v3.append(
                {
                    "match_id": match_id,
                    "won": bool(item.get("won")),
                    "kungfu": self._translate_kungfu_name(item.get("kungfu") or item.get("kungfu_name")),
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
        recent_matches = history_3v3[: self.max_recent_matches]
        wins = sum(1 for item in recent_matches if item.get("won"))
        total = len(recent_matches)
        missing_match_id_count = sum(1 for item in recent_matches if not item.get("match_id"))
        missing_avg_grade_count = sum(1 for item in recent_matches if item.get("avg_grade") is None)

        logger.info(
            "JJC 角色近期构建完成: server={} name={} history_total={} recent_total={} missing_match_id_count={} missing_avg_grade_count={} identity_source={}",
            server,
            name,
            len(history_3v3),
            total,
            missing_match_id_count,
            missing_avg_grade_count,
            identity.get("source"),
        )
        if history_3v3:
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
            "summary": {
                "total_matches": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": round((wins / total) * 100, 1) if total else None,
                "score": recent_matches[0].get("total_mmr") if recent_matches else None,
                "ranking": None,
                "grade": recent_matches[0].get("avg_grade") if recent_matches else None,
                "mvp_count": sum(1 for item in recent_matches if item.get("mvp")),
                "window_start": recent_matches[-1].get("match_time") if recent_matches else None,
                "window_end": recent_matches[0].get("match_time") if recent_matches else None,
            },
            "recent_matches": recent_matches,
        }

    async def get_match_detail(self, *, match_id: Union[int, str]) -> dict[str, Any]:
        normalized_match_id = _coerce_int(match_id)
        if normalized_match_id is None:
            return {"error": True, "message": "invalid_match_id"}

        cached = await self.cache_repo.load_match_detail(normalized_match_id)
        if cached:
            data = dict(cached.get("data") or {})
            data["cache"] = {"hit": True, "cached_at": cached.get("cached_at")}
            return data

        logger.info("加载 JJC 对局详情: match_id={}", normalized_match_id)
        detail = await self._run_serialized_tuilan_query(
            f"match_detail:{normalized_match_id}",
            self.match_detail_client.get_match_detail_obj,
            match_id=normalized_match_id,
        )
        if not isinstance(detail, MatchDetailResponse):
            return {"error": True, "message": "invalid_response"}
        if detail.code != 0 or not detail.data:
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
        cached_at = time.time()
        await self.cache_repo.save_match_detail(normalized_match_id, {"cached_at": cached_at, "data": payload})
        payload["cache"] = {"hit": False, "cached_at": cached_at}
        return payload
