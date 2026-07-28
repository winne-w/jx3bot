"""Fetch a role's equipment snapshot from its latest 3v3 match."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> str:
    return "".join(_text(value).split()).casefold()


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    return {}


class JjcMatchEquipmentService:
    """Keep the latest-match equipment flow independent of QQ and rendering."""

    def __init__(
        self,
        *,
        identity_repo: Any,
        role_detail_fetcher: Callable[..., Awaitable[Dict[str, Any]]],
        role_indicator_fetcher: Callable[..., Any],
        match_history_client: Any,
        match_detail_client: Any,
        tuilan_request: Callable[[str, Dict[str, Any]], Any],
        cache_repo: Optional[Any] = None,
    ) -> None:
        self.identity_repo = identity_repo
        self.role_detail_fetcher = role_detail_fetcher
        self.role_indicator_fetcher = role_indicator_fetcher
        self.match_history_client = match_history_client
        self.match_detail_client = match_detail_client
        self.tuilan_request = tuilan_request
        self.cache_repo = cache_repo
        self._endpoint_locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, endpoint: str) -> asyncio.Lock:
        lock = self._endpoint_locks.get(endpoint)
        if lock is None:
            lock = asyncio.Lock()
            self._endpoint_locks[endpoint] = lock
        return lock

    async def _run_sync(self, endpoint: str, func: Callable[..., Any], **kwargs: Any) -> Any:
        async with self._lock_for(endpoint):
            return await asyncio.to_thread(func, **kwargs)

    async def _fetch_role_detail(self, server: str, name: str) -> Any:
        async with self._lock_for("role_detail"):
            return await self.role_detail_fetcher(server=server, name=name)

    @staticmethod
    def _has_tuilan_seed(identity: Any) -> bool:
        return isinstance(identity, dict) and bool(
            _text(identity.get("role_id") or identity.get("game_role_id"))
            and _text(identity.get("zone"))
        )

    @staticmethod
    def _parse_role_detail(response: Any) -> Optional[Dict[str, str]]:
        if not isinstance(response, dict) or _int(response.get("code")) != 0:
            return None
        data = response.get("data")
        if not isinstance(data, dict):
            return None
        role_id = _text(data.get("roleId") or data.get("role_id"))
        zone = _text(data.get("zoneName") or data.get("zone"))
        global_id = _text(data.get("globalId") or data.get("global_id"))
        if not role_id or not zone:
            return None
        return {"role_id": role_id, "zone": zone, "global_id": global_id}

    def _indicator_request(self, role_id: str, zone: str, server: str, name: str) -> Any:
        return self.role_indicator_fetcher(
            role_id,
            zone,
            server,
            tuilan_request=self.tuilan_request,
            rank=None,
            name=name,
        )

    @staticmethod
    def _global_role_id(indicator: Any) -> Optional[str]:
        if not isinstance(indicator, dict) or indicator.get("error"):
            return None
        data = indicator.get("data")
        if not isinstance(data, dict):
            return None
        role_info = data.get("role_info") or data.get("roleInfo")
        if not isinstance(role_info, dict):
            return None
        value = _text(role_info.get("global_role_id") or role_info.get("globalRoleId"))
        return value if value.startswith("SK01") else None

    @staticmethod
    def _latest_3v3(history: Any) -> Optional[Dict[str, Any]]:
        items = history.get("data") if isinstance(history, dict) else None
        if not isinstance(items, list):
            return None
        candidates: List[tuple] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            match_type = _int(item.get("pvp_type") or item.get("pvpType") or item.get("type"))
            match_id = _int(item.get("match_id") or item.get("matchId") or item.get("id"))
            if match_type != 3 or match_id is None or match_id <= 0:
                continue
            match_time = _int(item.get("match_time") or item.get("start_time") or item.get("startTime"))
            if match_time is None:
                continue
            candidates.append((match_time, match_id, item))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
        match_time, match_id, item = candidates[0]
        return {"match_id": match_id, "match_time": match_time, "raw": item}

    @staticmethod
    def _find_player(detail: Any, server: str, name: str) -> Optional[Any]:
        data = _value(detail, "data")
        if data is None:
            return None
        matches: List[Any] = []
        for team_name in ("team1", "team2"):
            team = _value(data, team_name)
            players = _value(team, "players_info", []) if team is not None else []
            if not isinstance(players, list):
                continue
            for player in players:
                if _normalize(_value(player, "server")) == _normalize(server) and _normalize(_value(player, "role_name")) == _normalize(name):
                    matches.append(player)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _failure(code: str, message: str) -> Dict[str, Any]:
        return {"ok": False, "code": code, "message": message}

    @staticmethod
    def _snapshot(player: Any, server: str, name: str, match: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "server": _text(_value(player, "server")) or server,
            "role_name": _text(_value(player, "role_name")) or name,
            "match_id": match["match_id"],
            "match_time": match["match_time"],
            "kungfu": _text(_value(player, "kungfu")),
            "equip_score": _value(player, "equip_score"),
            "equip_strength_score": _value(player, "equip_strength_score"),
            "stone_score": _value(player, "stone_score"),
            "armors": [_as_dict(item) for item in (_value(player, "armors", []) or [])],
            "metrics": [_as_dict(item) for item in (_value(player, "metrics", []) or [])],
            "body_qualities": [_as_dict(item) for item in (_value(player, "body_qualities", []) or [])],
        }

    async def query(self, *, server: str, name: str) -> Dict[str, Any]:
        identity = await self.identity_repo.find_best_by_name_with_id(server, name)
        if not self._has_tuilan_seed(identity):
            try:
                response = await self._fetch_role_detail(server, name)
            except Exception:
                response = None
            detail = self._parse_role_detail(response)
            if detail is None:
                return self._failure("role_identity_unavailable", "未找到可用的角色身份信息")
            identity = await self.identity_repo.upsert_from_jx3api_role_detail(
                server,
                name,
                zone=detail["zone"],
                role_id=detail["role_id"],
                global_id=detail["global_id"] or None,
                cache_repo=self.cache_repo,
            )
        if not self._has_tuilan_seed(identity):
            return self._failure("role_identity_unavailable", "未找到可用的角色身份信息")

        role_id = _text(identity.get("role_id") or identity.get("game_role_id"))
        zone = _text(identity.get("zone"))
        try:
            indicator = await self._run_sync(
                "role_indicator", self._indicator_request, role_id=role_id, zone=zone, server=server, name=name,
            )
        except Exception:
            indicator = None
        global_role_id = self._global_role_id(indicator)
        if global_role_id is None:
            return self._failure("indicator_unavailable", "角色 indicator 查询失败")

        try:
            history = await self._run_sync(
                "match_history", self.match_history_client.get_mine_match_history,
                global_role_id=global_role_id, size=20, cursor=0,
            )
        except Exception:
            history = None
        match = self._latest_3v3(history)
        if match is None:
            return self._failure("no_recent_3v3", "未找到最近 3v3 对局")

        try:
            detail = await self._run_sync(
                "match_detail", self.match_detail_client.get_match_detail_obj, match_id=match["match_id"],
            )
        except Exception:
            detail = None
        if detail is None or _int(_value(detail, "code")) != 0 or _value(detail, "data") is None:
            return self._failure("match_detail_unavailable", "最近 3v3 对局详情不可用")
        player = self._find_player(detail, server, name)
        if player is None:
            return self._failure("target_player_not_found", "最近 3v3 对局未找到目标角色")
        armors = _value(player, "armors", [])
        if not isinstance(armors, list) or not armors:
            return self._failure("equipment_unavailable", "最近 3v3 对局未找到可用装备快照")
        return {"ok": True, "snapshot": self._snapshot(player, server, name, match)}
