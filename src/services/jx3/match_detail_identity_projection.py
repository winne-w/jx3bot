from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _pick_str(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


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


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_role_name(name: Any, server: Optional[str]) -> str:
    text = _pick_str(name) or ""
    if not text:
        return ""
    if "·" not in text:
        return text
    left, right = text.rsplit("·", 1)
    if server and right == server:
        return left
    return text


def _extract_match_time(payload: Dict[str, Any], detail: Dict[str, Any]) -> Optional[int]:
    for source in (payload, detail):
        match_time = _coerce_int(
            source.get("match_time")
            or source.get("matchTime")
            or source.get("start_time")
            or source.get("startTime")
            or source.get("time")
        )
        if match_time is not None:
            return match_time
    return None


@dataclass(frozen=True)
class MatchDetailIdentityProjectionService:
    """Project cached JJC match-detail players into role identity and sync queue."""

    identity_repo: Any
    sync_repo: Any
    kungfu_pinyin_to_chinese: Optional[Dict[str, str]] = None

    def _translate_kungfu(self, value: Any) -> Optional[str]:
        text = _pick_str(value)
        if not text:
            return None
        mapping = self.kungfu_pinyin_to_chinese or {}
        return mapping.get(text, text)

    def _iter_players(self, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
        players: List[Dict[str, Any]] = []
        for team_key in ("team1", "team2"):
            team = detail.get(team_key)
            if not isinstance(team, dict):
                continue
            players_info = team.get("players_info") or []
            if not isinstance(players_info, list):
                continue
            for player in players_info:
                if isinstance(player, dict):
                    players.append(player)
        return players

    async def project_payload(
        self,
        *,
        match_id: Any,
        payload: Optional[Dict[str, Any]],
        source: str = "match_detail_cache",
        priority: int = 0,
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"projected": 0, "skipped": True, "message": "payload_missing"}

        detail = payload.get("detail")
        if not isinstance(detail, dict):
            return {"projected": 0, "skipped": True, "message": "detail_missing"}

        players = self._iter_players(detail)
        if not players:
            return {"projected": 0, "skipped": True, "message": "players_missing"}

        observed_match_time = _extract_match_time(payload, detail)
        observed_at = datetime.now(timezone.utc)
        projected = 0
        skipped = 0
        queued = 0

        for player in players:
            server = _pick_str(
                player.get("server"),
                player.get("server_name"),
                player.get("serverName"),
            )
            name = _normalize_role_name(
                _pick_str(player.get("role_name"), player.get("roleName"), player.get("name")),
                server,
            )
            if not server or not name:
                skipped += 1
                continue

            role_id = _pick_str(
                player.get("role_id"),
                player.get("roleId"),
                player.get("game_role_id"),
                player.get("gameRoleId"),
            )
            game_role_id = _pick_str(player.get("game_role_id"), player.get("gameRoleId"), role_id)
            identity_started_at = time.perf_counter()
            identity = await _maybe_await(
                self.identity_repo.upsert_from_match_detail_with_id(
                    server=server,
                    name=name,
                    zone=_pick_str(player.get("zone")),
                    game_role_id=game_role_id,
                    global_role_id=_pick_str(player.get("global_role_id"), player.get("globalRoleId")),
                    role_id=role_id,
                    person_id=_pick_str(player.get("person_id"), player.get("personId")),
                    global_id=_pick_str(player.get("global_id"), player.get("globalId")),
                    observed_at=observed_at,
                    observed_match_time=observed_match_time,
                )
            )
            identity_ms = int((time.perf_counter() - identity_started_at) * 1000)
            projected += 1

            queue_ms = 0
            queued_this_player = False
            if hasattr(self.sync_repo, "upsert_identity_queue_candidate") and isinstance(identity, dict):
                queue_started_at = time.perf_counter()
                await _maybe_await(
                    self.sync_repo.upsert_identity_queue_candidate(
                        identity_id=identity.get("_id"),
                        identity_key=identity.get("identity_key"),
                        server=identity.get("server") or server,
                        name=identity.get("name") or name,
                        normalized_server=identity.get("normalized_server") or server,
                        normalized_name=identity.get("normalized_name") or name,
                        global_id=identity.get("global_id"),
                        global_role_id=identity.get("global_role_id"),
                        role_id=identity.get("role_id") or role_id,
                        game_role_id=identity.get("game_role_id") or game_role_id,
                        person_id=identity.get("person_id"),
                        zone=identity.get("zone"),
                        source=source,
                        priority=priority,
                    )
                )
                queue_ms = int((time.perf_counter() - queue_started_at) * 1000)
                queued += 1
                queued_this_player = True

            logger.info(
                "JJC 对局详情身份投影玩家耗时: match_id=%s server=%s name=%s global_id=%s "
                "identity_ms=%s queue_ms=%s queued=%s",
                match_id,
                server,
                name,
                _pick_str(player.get("global_id"), player.get("globalId")),
                identity_ms,
                queue_ms,
                queued_this_player,
            )

        result = {"projected": projected, "skipped_players": skipped, "queued": queued}
        logger.info(
            "JJC 对局详情身份投影完成: match_id=%s projected=%s skipped=%s queued=%s",
            match_id,
            projected,
            skipped,
            queued,
        )
        return result
