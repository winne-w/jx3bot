from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.services.jx3.tuilan_rate_limit import random_sleep
from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo

from nonebot import logger


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


def build_identity_key(
    *,
    global_role_id: Optional[str] = None,
    zone: Optional[str] = None,
    role_id: Optional[str] = None,
    server: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    """构建角色身份键。

    优先级:
      1. global:{global_role_id}
      2. game:{zone}:{role_id}
      3. name:{server}:{name}

    Raises:
        ValueError: 无法从提供的参数构建任何有效 key。
    """
    if global_role_id:
        return f"global:{global_role_id}"
    if zone and role_id:
        return f"game:{zone}:{role_id}"
    if server and name:
        return f"name:{server}:{name}"
    raise ValueError(
        "无法构建 identity_key：至少需要 global_role_id，或 zone+role_id，或 server+name"
    )


def extract_match_id_from_history(item: dict) -> Optional[int]:
    """从历史 item 中提取 match_id。

    依次尝试键名: match_id, matchId, matchID, id。
    """
    for key in ("match_id", "matchId", "matchID", "id"):
        value = _coerce_int(item.get(key))
        if value is not None:
            return value
    return None


def extract_match_time_from_history(item: dict) -> Optional[int]:
    """从历史 item 中提取 match_time（Unix 秒）。

    依次尝试键名: match_time, matchTime, start_time, startTime, time。
    """
    return _coerce_int(
        item.get("match_time")
        or item.get("matchTime")
        or item.get("start_time")
        or item.get("startTime")
        or item.get("time")
    )


def extract_pvp_type_from_history(item: dict) -> Optional[int]:
    """从历史 item 中提取 pvp_type。

    依次尝试键名: pvpType, pvp_type, type。
    3 表示 3v3。
    """
    return _coerce_int(
        item.get("pvpType")
        or item.get("pvp_type")
        or item.get("type")
    )


def normalize_match_detail_role_name(role_name: Any, server: Any) -> str:
    """去掉角色名中末尾的服务器后缀。

    规则：先 strip。如果不含 · 则直接返回；如果包含则只按最后一个 · 分割。
    若分割后右侧 trim 后等于 server trim 后且左侧非空，返回 trim 后的左侧；
    否则保持原 trim 后的角色名。
    """
    name = str(role_name or "").strip()
    server_name = str(server or "").strip()
    if not name or "·" not in name:
        return name

    left, right = name.rsplit("·", 1)
    left = left.strip()
    right = right.strip()
    if left and server_name and right == server_name:
        return left
    return name


def normalize_role_name(role_name: Any, server: Any) -> str:
    """兼容别名，统一复用对局详情角色名规范化逻辑。"""
    return normalize_match_detail_role_name(role_name, server)


def extract_players_from_detail(detail_data: dict) -> list[dict]:
    """从对局详情 payload 提取双方所有角色。

    从 team1.players_info 和 team2.players_info 提取，每个玩家返回包含以下字段的 dict：
      - role_name
      - global_role_id
      - role_id
      - person_id
      - zone
      - server

    按 global_role_id、zone+role_id、server+role_name 逐级构建去重键。
    """
    seen: set[str] = set()
    players: list[dict] = []

    for team_key in ("team1", "team2"):
        team = detail_data.get(team_key)
        if not isinstance(team, dict):
            continue
        players_info = team.get("players_info")
        if not isinstance(players_info, list):
            continue
        for player in players_info:
            if not isinstance(player, dict):
                continue
            global_role_id = str(player.get("global_role_id") or "").strip()
            role_id = str(player.get("role_id") or "").strip()
            person_id = str(player.get("person_id") or "").strip()
            zone = str(player.get("zone") or "").strip()
            server = str(player.get("server") or "").strip()
            role_name = normalize_role_name(player.get("role_name"), server)
            if global_role_id:
                dedupe_key = f"global:{global_role_id}"
            elif zone and role_id:
                dedupe_key = f"game:{zone}:{role_id}"
            elif server and role_name:
                dedupe_key = f"name:{server}:{role_name}"
            else:
                continue
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            players.append({
                "role_name": role_name,
                "global_role_id": global_role_id,
                "role_id": role_id,
                "person_id": person_id,
                "zone": zone,
                "server": server,
            })

    return players


def is_beyond_stop_time(match_time: Optional[int], stop_time: int) -> bool:
    """判断 match_time 是否已达到或超过停止水位。

    返回 match_time <= stop_time。
    match_time 为 None 时视为不安全，返回 False。
    """
    if match_time is None:
        return False
    return match_time <= stop_time


def is_before_season_start(match_time: Optional[int], season_start_time: int) -> bool:
    """判断 match_time 是否早于赛季开始时间。

    返回 match_time < season_start_time。
    """
    if match_time is None:
        return False
    return match_time < season_start_time


def compute_page_fingerprint(matches: list[dict]) -> str:
    """对一页对局列表生成指纹。

    将所有 match_id 提取、排序后用逗号连接。用于安全阀检测连续相同页面。
    """
    match_ids: list[int] = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        match_id = extract_match_id_from_history(item)
        if match_id is not None:
            match_ids.append(match_id)
    match_ids.sort()
    return ",".join(str(mid) for mid in match_ids)


def filter_3v3_matches(history_items: list[dict]) -> list[dict]:
    """只保留 pvp_type == 3 的对局。

    当 pvp_type 为 None 时保留——兼容旧数据可能缺少此字段。
    """
    result: list[dict] = []
    for item in history_items:
        if not isinstance(item, dict):
            continue
        pvp_type = extract_pvp_type_from_history(item)
        if pvp_type is None or pvp_type == 3:
            result.append(item)
    return result


def extract_history_items(payload: dict) -> List[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("list", "items", "matches", "records", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def extract_identity_from_person_history(payload: dict, person_id: Optional[str] = None) -> Dict[str, Any]:
    """从 person-history 响应中提取身份字段。

    推栏该接口按时间倒序返回对局记录；每条记录通常包含 global_role_id、
    person_id、role_name、server、zone。优先选择 person_id 匹配的第一条。
    """
    items = extract_history_items(payload)
    expected_person_id = str(person_id or "").strip()
    for item in items:
        item_person_id = str(item.get("person_id") or "").strip()
        if expected_person_id and item_person_id and item_person_id != expected_person_id:
            continue
        global_role_id = str(item.get("global_role_id") or item.get("globalRoleId") or "").strip()
        role_id = str(item.get("role_id") or item.get("roleId") or "").strip()
        zone = str(item.get("zone") or "").strip()
        server = str(item.get("server") or "").strip()
        role_name = normalize_role_name(
            item.get("role_name") or item.get("roleName"),
            server,
        )
        if global_role_id or role_id or zone or server or role_name:
            return {
                "global_role_id": global_role_id,
                "role_id": role_id,
                "game_role_id": role_id,
                "zone": zone,
                "server": server,
                "role_name": role_name,
                "person_id": item_person_id,
                "source": "person_history",
            }
    return {}


def parse_season_start_timestamp(season_start_str: str) -> int:
    """将 "2026-04-24" 格式的日期字符串转为 Unix 时间戳（秒）。

    使用北京时间（UTC+8）。
    """
    beijing_tz = timezone(timedelta(hours=8))
    dt = datetime.strptime(season_start_str, "%Y-%m-%d").replace(tzinfo=beijing_tz)
    return int(dt.timestamp())


class JjcMatchDataSyncService:
    """JJC 对局数据同步管理服务。

    提供角色管理、单轮同步、暂停/恢复、状态查询等管理用例。
    """

    def __init__(
        self,
        repo: JjcSyncRepo,
        current_season: str,
        current_season_start: str,
        match_history_client: Optional[Any] = None,
        inspect_service: Optional[Any] = None,
        identity_repo: Optional[Any] = None,
        person_match_history_client: Optional[Any] = None,
        sleep_func: Callable[[], Awaitable[None]] = random_sleep,
        page_size: int = 20,
        max_pages_per_role: int = 300,
        lease_seconds: int = 1800,
    ) -> None:
        self._repo = repo
        self._current_season = current_season
        self._season_start_time = parse_season_start_timestamp(current_season_start)
        self._match_history_client = match_history_client
        self._inspect_service = inspect_service
        self._identity_repo = identity_repo
        self._person_match_history_client = person_match_history_client
        self._sleep_func = sleep_func
        self._page_size = page_size
        self._max_pages_per_role = max_pages_per_role
        self._lease_seconds = lease_seconds
        self._background_task: Optional[asyncio.Task] = None
        self._last_background_summary: Optional[Dict[str, Any]] = None

    async def run_once(
        self,
        mode: str = "incremental_or_full",
        limit: int = 3,
    ) -> Dict[str, Any]:
        """执行一轮同步，由管理员命令显式触发。"""
        started_at = time.time()
        summary: Dict[str, Any] = {
            "error": False,
            "mode": mode,
            "processed_roles": 0,
            "discovered_matches": 0,
            "saved_details": 0,
            "skipped_details": 0,
            "failed_details": 0,
            "unavailable_details": 0,
            "failed_roles": 0,
            "recovered_leases": 0,
            "errors": [],
            "elapsed_seconds": 0.0,
        }

        if mode not in ("incremental_or_full", "full", "incremental"):
            return {"error": True, "message": "invalid_mode"}
        if limit < 1:
            return {"error": True, "message": "invalid_limit"}
        if self._match_history_client is None or self._inspect_service is None:
            return {"error": True, "message": "sync_dependencies_not_configured"}

        try:
            if await self._repo.get_paused():
                summary["paused"] = True
                return self._finish_summary(summary, started_at)

            summary["recovered_leases"] = await self._repo.recover_expired_leases()
            lease_owner = f"jjc-sync:{uuid.uuid4()}"
            roles = await self._repo.claim_next_roles(
                limit=limit,
                lease_owner=lease_owner,
                lease_seconds=self._lease_seconds,
            )

            for role in roles:
                role_result = await self._sync_one_role(
                    role=role,
                    mode=mode,
                    lease_owner=lease_owner,
                )
                summary["processed_roles"] += 1
                for key in ("discovered_matches", "saved_details", "skipped_details", "failed_details", "unavailable_details"):
                    summary[key] += role_result.get(key, 0)
                if role_result.get("error"):
                    summary["failed_roles"] += 1
                    summary["errors"].append(role_result.get("message", "unknown_error"))
        except Exception as exc:
            logger.warning("JJC 同步本轮执行失败: error={}", exc)
            summary["error"] = True
            summary["message"] = str(exc)
            summary["errors"].append(str(exc))

        return self._finish_summary(summary, started_at)

    @staticmethod
    def _finish_summary(summary: Dict[str, Any], started_at: float) -> Dict[str, Any]:
        summary["elapsed_seconds"] = round(time.time() - started_at, 3)
        return summary

    async def run_until_idle(
        self,
        mode: str = "incremental_or_full",
        limit: int = 20,
        max_rounds: Optional[int] = None,
        max_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """连续执行多轮同步，直到队列暂时无可执行角色或达到保护上限。"""
        started_at = time.time()
        rounds_limit = max_rounds if max_rounds is not None else 1000000
        summary: Dict[str, Any] = {
            "error": False,
            "mode": mode,
            "limit": limit,
            "max_rounds": max_rounds,
            "max_seconds": max_seconds,
            "rounds": 0,
            "processed_roles": 0,
            "discovered_matches": 0,
            "saved_details": 0,
            "skipped_details": 0,
            "failed_details": 0,
            "unavailable_details": 0,
            "failed_roles": 0,
            "recovered_leases": 0,
            "errors": [],
            "stopped_reason": "",
            "elapsed_seconds": 0.0,
        }

        if limit < 1:
            return {"error": True, "message": "invalid_limit"}
        if rounds_limit < 1:
            return {"error": True, "message": "invalid_rounds"}
        if max_seconds < 1:
            return {"error": True, "message": "invalid_max_seconds"}

        while summary["rounds"] < rounds_limit:
            elapsed = time.time() - started_at
            if elapsed >= max_seconds:
                summary["stopped_reason"] = "max_seconds_reached"
                break

            result = await self.run_once(mode=mode, limit=limit)
            summary["rounds"] += 1

            for key in (
                "processed_roles",
                "discovered_matches",
                "saved_details",
                "skipped_details",
                "failed_details",
                "unavailable_details",
                "failed_roles",
                "recovered_leases",
            ):
                summary[key] += result.get(key, 0)

            errors = result.get("errors") or []
            if errors:
                summary["errors"].extend(errors)

            if result.get("error"):
                summary["error"] = True
                summary["message"] = result.get("message", "unknown_error")
                summary["stopped_reason"] = "error"
                break
            if result.get("paused"):
                summary["paused"] = True
                summary["stopped_reason"] = "paused"
                break
            if result.get("processed_roles", 0) <= 0:
                summary["stopped_reason"] = "idle"
                break

        if not summary["stopped_reason"]:
            summary["stopped_reason"] = "max_rounds_reached"
        return self._finish_summary(summary, started_at)

    async def start_background_run(
        self,
        mode: str = "incremental_or_full",
        limit: int = 20,
        max_rounds: Optional[int] = None,
        max_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """启动后台批量同步任务。"""
        if self._background_task is not None and not self._background_task.done():
            return {"error": True, "message": "background_sync_already_running"}
        if limit < 1:
            return {"error": True, "message": "invalid_limit"}
        if max_rounds is not None and max_rounds < 1:
            return {"error": True, "message": "invalid_rounds"}
        if max_seconds < 1:
            return {"error": True, "message": "invalid_max_seconds"}

        self._background_task = asyncio.create_task(
            self._run_background(
                mode=mode,
                limit=limit,
                max_rounds=max_rounds,
                max_seconds=max_seconds,
            )
        )
        return {
            "error": False,
            "message": "background_sync_started",
            "mode": mode,
            "limit": limit,
            "max_rounds": max_rounds,
            "max_seconds": max_seconds,
        }

    async def _run_background(
        self,
        mode: str,
        limit: int,
        max_rounds: Optional[int],
        max_seconds: int,
    ) -> None:
        try:
            self._last_background_summary = await self.run_until_idle(
                mode=mode,
                limit=limit,
                max_rounds=max_rounds,
                max_seconds=max_seconds,
            )
        except Exception as exc:
            logger.warning("JJC 后台批量同步异常: error={}", exc)
            self._last_background_summary = {
                "error": True,
                "message": str(exc),
                "mode": mode,
                "limit": limit,
                "max_rounds": max_rounds,
                "max_seconds": max_seconds,
                "stopped_reason": "exception",
                "elapsed_seconds": 0.0,
            }

    async def _sync_one_role(
        self,
        role: Dict[str, Any],
        mode: str,
        lease_owner: str,
    ) -> Dict[str, Any]:
        identity_key = str(role.get("identity_key") or "")
        server = str(role.get("server") or "")
        name = str(role.get("name") or "")
        global_role_id = str(role.get("global_role_id") or "").strip()
        if not identity_key:
            return {"error": True, "message": "role_missing_identity_key"}
        if not global_role_id:
            identity = await self._resolve_role_identity_from_person_history(role)
            if not str(identity.get("global_role_id") or "").strip():
                identity = await self._resolve_role_identity_for_sync(role)
            global_role_id = str(identity.get("global_role_id") or "").strip()
            if not global_role_id:
                message = f"{server}/{name} 缺少 global_role_id，无法同步推栏战局历史"
                await self._repo.release_role_failure(identity_key, message)
                return {"error": True, "message": message}
            await self._repo.update_role_identity_fields(
                identity_key=identity_key,
                global_role_id=global_role_id,
                role_id=str(identity.get("role_id") or identity.get("game_role_id") or "").strip() or None,
                person_id=str(identity.get("person_id") or role.get("person_id") or "").strip() or None,
                zone=str(identity.get("zone") or "").strip() or None,
                identity_source=str(identity.get("source") or "").strip() or None,
            )
            await self._upsert_role_identity_from_resolved(server, name, identity)

        run_upper_time = int(time.time())
        stop_time = self._resolve_stop_time(role, mode)
        cursor = 0
        page_index = 0
        previous_fingerprint = ""
        repeated_fingerprint_count = 0
        oldest_synced_match_time: Optional[int] = None
        latest_seen_match_time: Optional[int] = None
        reached_boundary = False
        reached_season_start = False
        result: Dict[str, Any] = {
            "error": False,
            "discovered_matches": 0,
            "saved_details": 0,
            "skipped_details": 0,
            "failed_details": 0,
            "unavailable_details": 0,
        }

        try:
            logger.info("JJC 开始同步角色: {} / {}", server, name)
            while page_index < self._max_pages_per_role:
                await self._sleep_func()
                payload = await asyncio.to_thread(
                    self._match_history_client.get_mine_match_history,
                    global_role_id=global_role_id,
                    size=self._page_size,
                    cursor=cursor,
                )
                if not isinstance(payload, dict) or payload.get("error"):
                    raise RuntimeError(str(payload.get("error") if isinstance(payload, dict) else "invalid_history_response"))

                history_items = extract_history_items(payload)
                if not history_items:
                    reached_boundary = True
                    break

                fingerprint = compute_page_fingerprint(history_items)
                if fingerprint and fingerprint == previous_fingerprint:
                    repeated_fingerprint_count += 1
                else:
                    repeated_fingerprint_count = 0
                previous_fingerprint = fingerprint
                if repeated_fingerprint_count >= 2:
                    raise RuntimeError("history_repeated_page_safety_limit")

                should_stop_after_page = False
                for item in filter_3v3_matches(history_items):
                    match_id = extract_match_id_from_history(item)
                    match_time = extract_match_time_from_history(item)
                    if match_time is not None:
                        if latest_seen_match_time is None or match_time > latest_seen_match_time:
                            latest_seen_match_time = match_time
                        if oldest_synced_match_time is None or match_time < oldest_synced_match_time:
                            oldest_synced_match_time = match_time

                    if stop_time is not None and is_beyond_stop_time(match_time, stop_time):
                        reached_boundary = True
                        should_stop_after_page = True
                        break
                    if is_before_season_start(match_time, self._season_start_time):
                        reached_boundary = True
                        reached_season_start = True
                        should_stop_after_page = True
                        break
                    if match_id is None:
                        continue

                    marked = await self._repo.mark_match_discovered(
                        match_id=match_id,
                        match_time=match_time,
                        source_identity_key=identity_key,
                        source_server=server,
                        source_role_name=name,
                    )
                    if marked:
                        result["discovered_matches"] += 1
                    detail_result = await self._sync_match_detail(
                        match_id=match_id,
                        match_time=match_time,
                        lease_owner=lease_owner,
                        server=server,
                        name=name,
                    )
                    if detail_result == "saved":
                        result["saved_details"] += 1
                    elif detail_result == "skipped":
                        result["skipped_details"] += 1
                    elif detail_result == "failed":
                        result["failed_details"] += 1
                    elif detail_result == "unavailable":
                        result["unavailable_details"] += 1

                if should_stop_after_page:
                    break
                if len(history_items) < self._page_size:
                    reached_boundary = True
                    break
                cursor += self._page_size
                page_index += 1

            if page_index >= self._max_pages_per_role and not reached_boundary:
                raise RuntimeError("history_max_pages_safety_limit")

            history_exhausted = bool(role.get("history_exhausted")) or reached_season_start
            await self._repo.release_role_success(
                identity_key=identity_key,
                full_synced_until_time=run_upper_time,
                oldest_synced_match_time=oldest_synced_match_time,
                latest_seen_match_time=latest_seen_match_time,
                history_exhausted=history_exhausted,
                season_id=self._current_season,
                last_cursor=cursor,
            )
            return result
        except Exception as exc:
            message = f"{server}/{name} 同步失败: {exc}"
            logger.warning(message)
            await self._repo.release_role_failure(identity_key, message)
            result["error"] = True
            result["message"] = message
            return result

    async def _resolve_role_identity_for_sync(self, role: Dict[str, Any]) -> Dict[str, Any]:
        server = str(role.get("server") or "").strip()
        name = str(role.get("name") or "").strip()
        if not server or not name or self._inspect_service is None:
            return {}

        resolver = getattr(self._inspect_service, "_resolve_role_identity", None)
        if not callable(resolver):
            return {}

        role_id = str(role.get("role_id") or "").strip()
        zone = str(role.get("zone") or "").strip()
        hints: Dict[str, Any] = {
            "global_role_id": str(role.get("global_role_id") or "").strip(),
            "role_id": role_id,
            "game_role_id": str(role.get("game_role_id") or role_id).strip(),
            "zone": zone,
        }

        try:
            await self._sleep_func()
            identity = await resolver(
                server=server,
                name=name,
                identity_hints=hints,
            )
        except Exception as exc:
            logger.warning(
                "JJC 同步角色身份补全失败: server={} name={} error={}",
                server,
                name,
                exc,
            )
            return {}

        if not isinstance(identity, dict) or identity.get("error"):
            return {}
        return identity

    async def _resolve_role_identity_from_person_history(self, role: Dict[str, Any]) -> Dict[str, Any]:
        person_id = str(role.get("person_id") or "").strip()
        if not person_id or self._person_match_history_client is None:
            return {}

        try:
            await self._sleep_func()
            payload = await asyncio.to_thread(
                self._person_match_history_client.get_person_match_history,
                person_id=person_id,
                size=20,
                cursor=0,
            )
        except Exception as exc:
            logger.warning(
                "JJC 同步通过 person-history 补全身份失败: person_id={} error={}",
                person_id,
                exc,
            )
            return {}

        if not isinstance(payload, dict) or payload.get("error"):
            return {}
        identity = extract_identity_from_person_history(payload, person_id)
        if not identity:
            return {}

        server = str(identity.get("server") or "").strip()
        role_name = str(identity.get("role_name") or "").strip()
        if server:
            identity["server"] = server
        if role_name:
            identity["name"] = role_name
        return identity

    async def _resolve_player_identity_from_local_repo(self, player: Dict[str, Any]) -> Dict[str, Any]:
        if self._identity_repo is None:
            return {}
        server = str(player.get("server") or "").strip()
        name = str(player.get("role_name") or "").strip()
        zone = str(player.get("zone") or "").strip()
        role_id = str(player.get("role_id") or "").strip()
        global_role_id = str(player.get("global_role_id") or "").strip()
        if not ((server and name) or (zone and role_id) or global_role_id):
            return {}
        try:
            doc = await self._identity_repo.resolve_best_identity(
                server=server,
                name=name,
                zone=zone or None,
                game_role_id=role_id or None,
                global_role_id=global_role_id or None,
            )
        except Exception as exc:
            logger.warning(
                "JJC 同步通过本地身份库补全玩家身份失败: server={} name={} error={}".format(
                    server, name, exc
                )
            )
            return {}
        if not doc:
            return {}
        if not (server and name) and zone and role_id:
            doc_zone = str(doc.get("zone") or "").strip()
            doc_role_id = str(doc.get("role_id") or doc.get("game_role_id") or "").strip()
            if doc_zone != zone or doc_role_id != role_id:
                return {}
        return {
            "global_role_id": str(doc.get("global_role_id") or "").strip(),
            "role_id": str(doc.get("role_id") or doc.get("game_role_id") or "").strip(),
            "game_role_id": str(doc.get("game_role_id") or doc.get("role_id") or "").strip(),
            "person_id": str(doc.get("person_id") or "").strip(),
            "zone": str(doc.get("zone") or "").strip(),
            "server": str(doc.get("server") or "").strip(),
            "role_name": str(doc.get("role_name") or doc.get("name") or "").strip(),
            "source": "local_identity",
        }

    @staticmethod
    def _backfill_player_from_identity(player: Dict[str, Any], identity: Dict[str, Any]) -> None:
        for source_key, target_key in (
            ("global_role_id", "global_role_id"),
            ("role_id", "role_id"),
            ("game_role_id", "role_id"),
            ("zone", "zone"),
            ("person_id", "person_id"),
        ):
            value = str(identity.get(source_key) or "").strip()
            if value and not str(player.get(target_key) or "").strip():
                player[target_key] = value
        server_value = str(identity.get("server") or "").strip()
        if server_value and not str(player.get("server") or "").strip():
            player["server"] = server_value
        normalized_server = str(player.get("server") or identity.get("server") or "").strip()
        name_value = normalize_role_name(
            identity.get("role_name") or identity.get("name"),
            normalized_server,
        )
        if name_value and not str(player.get("role_name") or "").strip():
            player["role_name"] = name_value
        # 回填后统一做一次规范化，确保不会残留带服务器后缀的角色名
        current_name = str(player.get("role_name") or "").strip()
        current_server = str(player.get("server") or "").strip()
        if current_name and current_server:
            player["role_name"] = normalize_role_name(current_name, current_server)

    async def _resolve_player_identity_from_person_history(self, player: Dict[str, Any]) -> Dict[str, Any]:
        if str(player.get("global_role_id") or "").strip():
            return {}
        person_id = str(player.get("person_id") or "").strip()
        if not person_id or self._person_match_history_client is None:
            return {}

        try:
            await self._sleep_func()
            payload = await asyncio.to_thread(
                self._person_match_history_client.get_person_match_history,
                person_id=person_id,
                size=20,
                cursor=0,
            )
        except Exception as exc:
            logger.warning(
                "JJC 同步通过 person-history 补全对局玩家身份失败: person_id={} error={}",
                person_id,
                exc,
            )
            return {}

        if not isinstance(payload, dict) or payload.get("error"):
            return {}
        return extract_identity_from_person_history(payload, person_id)

    async def _upsert_role_identity_from_resolved(
        self,
        server: str,
        name: str,
        identity: Dict[str, Any],
        observed_match_time: Optional[int] = None,
    ) -> None:
        if self._identity_repo is None:
            return

        global_role_id = str(identity.get("global_role_id") or "").strip() or None
        role_id = str(identity.get("role_id") or identity.get("game_role_id") or "").strip() or None
        person_id = str(identity.get("person_id") or "").strip() or None
        zone = str(identity.get("zone") or "").strip() or None
        if not global_role_id and not role_id and not zone and not person_id:
            return
        observed_at = (
            datetime.fromtimestamp(observed_match_time, tz=timezone.utc)
            if observed_match_time is not None
            else None
        )

        try:
            await self._identity_repo.upsert_from_match_detail(
                server=server,
                name=name,
                zone=zone,
                game_role_id=role_id,
                global_role_id=global_role_id,
                role_id=role_id,
                person_id=person_id,
                observed_at=observed_at,
            )
        except Exception as exc:
            logger.warning(
                "JJC 同步写入角色身份表失败: server={} name={} error={}",
                server,
                name,
                exc,
            )

    def _resolve_stop_time(self, role: Dict[str, Any], mode: str) -> Optional[int]:
        if mode == "full":
            return None
        full_synced_until_time = _coerce_int(role.get("full_synced_until_time"))
        if mode == "incremental":
            return full_synced_until_time
        return full_synced_until_time

    async def _sync_match_detail(
        self,
        match_id: int,
        match_time: Optional[int],
        lease_owner: str,
        server: str = "",
        name: str = "",
        max_attempts: int = 3,
    ) -> str:
        match_time_str = (
            datetime.fromtimestamp(match_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if match_time
            else "unknown"
        )
        logger.info(
            "JJC 同步对局详情: match_id={} match_time={} server={} name={}",
            match_id,
            match_time_str,
            server,
            name,
        )
        claim = await self._repo.claim_match_detail(
            match_id=match_id,
            lease_owner=lease_owner,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return "skipped"

        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                await self._sleep_func()
                payload = await self._inspect_service.get_match_detail(match_id=match_id)
                if not isinstance(payload, dict) or payload.get("error"):
                    message = payload.get("message") if isinstance(payload, dict) else "invalid_detail_response"
                    last_error = str(message)
                else:
                    detail = payload.get("detail")
                    if detail is None:
                        reason = str(payload.get("message") or "no data found")
                        code = payload.get("code") if payload.get("code") is not None else -1
                        await self._repo.mark_match_detail_unavailable(match_id, reason=reason, code=code)
                        return "unavailable"
                    await self._repo.mark_match_detail_saved(match_id)
                    if isinstance(detail, dict):
                        await self._enqueue_players_from_detail(detail, fallback_match_time=match_time)
                    return "saved"
            except Exception as exc:
                last_error = str(exc)

        await self._repo.mark_match_detail_failed(match_id, last_error)
        return "failed"

    async def _enqueue_players_from_detail(
        self,
        detail: Dict[str, Any],
        fallback_match_time: Optional[int] = None,
    ) -> None:
        detail_match_time = _coerce_int(detail.get("match_time")) or fallback_match_time
        for player in extract_players_from_detail(detail):
            if not str(player.get("global_role_id") or "").strip():
                identity = await self._resolve_player_identity_from_local_repo(player)
                if identity:
                    self._backfill_player_from_identity(player, identity)
                else:
                    person_identity = await self._resolve_player_identity_from_person_history(player)
                    if person_identity:
                        self._backfill_player_from_identity(player, person_identity)
            server = str(player.get("server") or "").strip()
            name = normalize_role_name(
                str(player.get("role_name") or "").strip(), server
            )
            if not server or not name:
                continue
            await self._upsert_role_identity_from_resolved(
                server,
                name,
                {
                    "global_role_id": str(player.get("global_role_id") or "").strip(),
                    "role_id": str(player.get("role_id") or "").strip(),
                    "game_role_id": str(player.get("role_id") or "").strip(),
                    "person_id": str(player.get("person_id") or "").strip(),
                    "zone": str(player.get("zone") or "").strip(),
                },
                observed_match_time=detail_match_time,
            )
            await self._repo.upsert_role(
                server=server,
                name=name,
                normalized_server=server,
                normalized_name=name,
                global_role_id=str(player.get("global_role_id") or "").strip() or None,
                role_id=str(player.get("role_id") or "").strip() or None,
                person_id=str(player.get("person_id") or "").strip() or None,
                zone=str(player.get("zone") or "").strip() or None,
                source="match_detail",
                priority=-10,
                season_id=self._current_season,
                season_start_time=self._season_start_time,
            )

    async def add_role(
        self,
        server: str,
        name: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        zone: Optional[str] = None,
        source: str = 'manual',
    ) -> Dict[str, Any]:
        """添加角色到同步队列。"""
        normalized_server = server.strip()
        normalized_name = name.strip()
        if not normalized_server or not normalized_name:
            return {"error": True, "message": "服务器和角色名不能为空"}

        try:
            await self._upsert_role_identity_from_resolved(
                normalized_server,
                normalized_name,
                {
                    "global_role_id": global_role_id or "",
                    "role_id": role_id or "",
                    "game_role_id": role_id or "",
                    "zone": zone or "",
                },
            )
            identity_key = await self._repo.upsert_role(
                server=server,
                name=name,
                normalized_server=normalized_server,
                normalized_name=normalized_name,
                global_role_id=global_role_id,
                role_id=role_id,
                zone=zone,
                source=source,
                season_id=self._current_season,
                season_start_time=self._season_start_time,
            )
            if not identity_key:
                return {"error": True, "message": "添加角色失败"}
            return {
                "error": False,
                "message": f"角色 {server}/{name} 已加入同步队列",
                "identity_key": identity_key,
            }
        except Exception as exc:
            logger.warning("add_role 失败: server={} name={} error={}", server, name, exc)
            return {"error": True, "message": f"添加角色失败: {exc}"}

    async def pause(self, reason: str = '') -> Dict[str, Any]:
        """暂停全局同步。"""
        success = await self._repo.set_paused(True, reason)
        if success:
            return {"error": False, "message": "同步已暂停" + (f"（{reason}）" if reason else "")}
        return {"error": True, "message": "暂停同步失败"}

    async def resume(self) -> Dict[str, Any]:
        """恢复全局同步。"""
        success = await self._repo.set_paused(False)
        if success:
            return {"error": False, "message": "同步已恢复"}
        return {"error": True, "message": "恢复同步失败"}

    async def status(self) -> Dict[str, Any]:
        """查询同步状态。"""
        try:
            paused = await self._repo.get_paused()
            counts = await self._repo.count_by_status()
            recent_errors = await self._repo.get_recent_errors(limit=5)
            return {
                "error": False,
                "paused": paused,
                "counts": counts,
                "recent_errors": recent_errors,
                "background_running": self._background_task is not None and not self._background_task.done(),
                "last_background_summary": self._last_background_summary,
            }
        except Exception as exc:
            logger.warning("status 查询失败: error={}", exc)
            return {"error": True, "message": f"查询状态失败: {exc}"}

    async def reset_role(self, server: str, name: str) -> Dict[str, Any]:
        """重置角色同步进度。"""
        normalized_server = server.strip()
        normalized_name = name.strip()
        if not normalized_server or not normalized_name:
            return {"error": True, "message": "服务器和角色名不能为空"}

        role = await self._repo.get_role_by_name(normalized_server, normalized_name)
        if role is None:
            return {"error": True, "message": f"未找到角色 {server}/{name}"}

        identity_key = role.get("identity_key", "")
        success = await self._repo.reset_role_progress(identity_key)
        if success:
            return {
                "error": False,
                "message": f"角色 {server}/{name} 同步进度已重置",
                "identity_key": identity_key,
            }
        return {"error": True, "message": f"重置角色 {server}/{name} 同步进度失败"}
