"""Build the compact, rebuildable JJC 3v3 match-fact projection.

This module deliberately has no database or framework dependency.  The caller
persists the returned active fact or tombstone with its own version/CAS policy.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.utils.jjc_match_fact import encode_combo_key, normalize_positive_int


_CANONICAL_SCORE_INT = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_TIME_KEYS = ("match_time", "matchTime", "start_time", "startTime", "time")
_AUDIT_FIELDS = frozenset(("schema_version", "source_cached_at", "source_hash", "projected_at"))


def _match_fact_source_projection() -> Dict[str, int]:
    """Return the minimal persisted-detail fields required to rebuild a fact."""
    projection = {
        "_id": 0,
        "match_id": 1,
        "cached_at": 1,
        "match_time": 1,
        "matchTime": 1,
        "start_time": 1,
        "startTime": 1,
        "time": 1,
        "data.unavailable": 1,
        "data.match_time": 1,
        "data.matchTime": 1,
        "data.start_time": 1,
        "data.startTime": 1,
        "data.time": 1,
        "data.detail.unavailable": 1,
        "data.detail.match_time": 1,
        "data.detail.matchTime": 1,
        "data.detail.start_time": 1,
        "data.detail.startTime": 1,
        "data.detail.time": 1,
        "data.detail.map": 1,
        "data.detail.map_name": 1,
        "data.detail.duration": 1,
        "data.detail.fight_seconds": 1,
        "data.detail.match_type": 1,
        "data.detail.matchType": 1,
        "data.detail.type": 1,
    }
    for detail_prefix in ("data", "data.detail"):
        for detail_field in (
            "map", "map_name", "duration", "fight_seconds",
            "match_type", "matchType", "type",
        ):
            projection["{}.{}".format(detail_prefix, detail_field)] = 1
        for basic_info_field in (
            "match_time", "matchTime", "start_time", "startTime", "time",
            "map", "map_name", "duration", "fight_seconds",
            "match_type", "matchType", "type",
        ):
            projection["{}.basic_info.{}".format(detail_prefix, basic_info_field)] = 1
        for team_key in ("team1", "team2"):
            projection["{}.{}.won".format(detail_prefix, team_key)] = 1
            for players_key in ("players_info", "players"):
                for player_field in (
                    "role_name", "server", "kungfu_id", "kungfu", "total_score", "score"
                ):
                    projection["{}.{}.{}.{}".format(
                        detail_prefix, team_key, players_key, player_field
                    )] = 1
    return projection


MATCH_FACT_SOURCE_PROJECTION = _match_fact_source_projection()


def match_fact_source_payload(document: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep source fields and actual-time aliases used by fact reconstruction."""
    payload = {"cached_at": document.get("cached_at"), "data": document.get("data")}
    for key in _TIME_KEYS:
        if key in document:
            payload[key] = document.get(key)
    return payload


def normalize_game_score(value: Any) -> Optional[int]:
    """Normalize one game score in the inclusive ``0..1000000`` range."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        integer_value = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        integer_value = int(value)
    elif isinstance(value, str) and _CANONICAL_SCORE_INT.fullmatch(value):
        integer_value = int(value)
    else:
        return None
    if 0 <= integer_value <= 1000000:
        return integer_value
    return None


def _mapping(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) else None


def _detail_parts(payload: Mapping[str, Any]) -> Tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    """Return outer payload, detail envelope, and the actual detail mapping."""
    envelope = _mapping(payload.get("data")) or payload
    detail = _mapping(envelope.get("detail"))
    if detail is None:
        detail = _mapping(payload.get("detail"))
    if detail is None:
        detail = envelope
    return payload, envelope, detail


def _first_positive_time(*mappings: Mapping[str, Any]) -> Optional[int]:
    for mapping in mappings:
        for key in _TIME_KEYS:
            value = normalize_positive_int(mapping.get(key))
            if value is not None:
                return value
    return None


def extract_match_time(payload: Mapping[str, Any]) -> Optional[int]:
    """Read the actual match time, never cache/projection/current time.

    A root-level compatibility time wins first, followed by the persisted
    business ``data`` envelope, detail, and then ``basic_info``.
    """
    if not isinstance(payload, Mapping):
        return None
    outer, envelope, detail = _detail_parts(payload)
    basic_info = _mapping(detail.get("basic_info")) or {}
    # Sync can add the actual occurrence time to the data envelope after an
    # older nested detail was fetched, so envelope deliberately outranks it.
    return _first_positive_time(outer, envelope, detail, basic_info)


def _source_cached_at(payload: Mapping[str, Any]) -> Optional[float]:
    """Keep the positive finite cache version without truncating sub-seconds."""
    value = payload.get("cached_at")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return value if math.isfinite(value) and value > 0 else None
    return None


def _canonical_source(source: Mapping[str, Any]) -> Dict[str, Any]:
    """Drop projection-only audit fields without modifying nested source data."""
    return {key: value for key, value in source.items() if key not in _AUDIT_FIELDS}


def build_source_hash(source_summary: Dict[str, Any]) -> str:
    """Return SHA-256 of sorted, compact UTF-8 canonical JSON source data."""
    canonical = json.dumps(
        _canonical_source(source_summary),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _optional_display_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        integer_value = int(value)
        return integer_value if integer_value >= 0 else None
    if isinstance(value, str) and _CANONICAL_SCORE_INT.fullmatch(value):
        return int(value)
    return None


def _first_mapping_value(mappings: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> Any:
    for mapping in mappings:
        for key in keys:
            if key in mapping and mapping.get(key) is not None:
                return mapping.get(key)
    return None


def _extract_match_type(detail: Mapping[str, Any]) -> Tuple[bool, Optional[int]]:
    basic_info = _mapping(detail.get("basic_info")) or {}
    raw = _first_mapping_value((detail, basic_info), ("match_type", "matchType", "type"))
    if raw is None:
        return False, None
    return True, normalize_positive_int(raw)


def _extract_players(team: Mapping[str, Any]) -> Optional[List[Mapping[str, Any]]]:
    players = team.get("players_info")
    if players is None:
        players = team.get("players")
    if not isinstance(players, list) or len(players) != 3:
        return None
    normalized_players: List[Mapping[str, Any]] = []
    for player in players:
        player_mapping = _mapping(player)
        if player_mapping is None:
            return None
        normalized_players.append(player_mapping)
    return normalized_players


def _normalized_player_scores(player: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[str]]:
    """Return normalized raw score fields and the selected game-score result."""
    total_score = normalize_game_score(player.get("total_score"))
    score = normalize_game_score(player.get("score"))
    if total_score is not None:
        return total_score, score, total_score, "total_score"
    if score is not None:
        return total_score, score, score, "score"
    return total_score, score, None, None


def _player_fact(player: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    kungfu_id = normalize_positive_int(player.get("kungfu_id"))
    if kungfu_id is None:
        return None
    _, _, game_score, score_source = _normalized_player_scores(player)
    return {
        "role_name": str(player.get("role_name") or ""),
        "server": str(player.get("server") or ""),
        "kungfu_id": kungfu_id,
        "kungfu": str(player.get("kungfu") or ""),
        "game_score": game_score,
        "score_source": score_source,
    }


def _combo_keys(kungfu_ids: Sequence[int]) -> List[str]:
    keys = set()
    for size in range(1, len(kungfu_ids) + 1):
        for subset in itertools.combinations(kungfu_ids, size):
            keys.add(encode_combo_key(list(subset)))
    return sorted(keys)


def _team_fact(team: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    players = _extract_players(team)
    if players is None:
        return None
    if not isinstance(team.get("won"), bool):
        return None
    projected_players: List[Dict[str, Any]] = []
    for player in players:
        projected_player = _player_fact(player)
        if projected_player is None:
            return None
        projected_players.append(projected_player)
    kungfu_ids = [player["kungfu_id"] for player in projected_players]
    scores = [player["game_score"] for player in projected_players]
    valid_scores = [score for score in scores if score is not None]
    score_sum = sum(valid_scores)
    score_count = len(valid_scores)
    score_complete = score_count == 3
    return {
        "won": team["won"],
        "players": projected_players,
        "kungfu_ids": kungfu_ids,
        "combo_keys": _combo_keys(kungfu_ids),
        "score_sum": score_sum,
        "score_count": score_count,
        "score_complete": score_complete,
        "score_avg": float(score_sum) / 3 if score_complete else None,
    }


def _source_player_summary(player: Any) -> Optional[Dict[str, Any]]:
    player_mapping = _mapping(player)
    if player_mapping is None:
        return None
    total_score, score, _, _ = _normalized_player_scores(player_mapping)
    return {
        "role_name": str(player_mapping.get("role_name") or ""),
        "server": str(player_mapping.get("server") or ""),
        "kungfu_id": normalize_positive_int(player_mapping.get("kungfu_id")),
        "kungfu": str(player_mapping.get("kungfu") or ""),
        "total_score": total_score,
        "score": score,
    }


def _source_team_summary(team: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if team is None:
        return None
    players = team.get("players_info")
    if players is None:
        players = team.get("players")
    return {
        "won": team.get("won") if isinstance(team.get("won"), bool) else None,
        "players": [_source_player_summary(player) for player in players] if isinstance(players, list) else None,
    }


def _source_summary(
    match_id: int,
    outer: Mapping[str, Any],
    detail: Mapping[str, Any],
    active: bool,
    invalid_reason: Optional[str],
) -> Dict[str, Any]:
    """Build the canonical source-only hash input; derived projection fields stay out."""
    basic_info = _mapping(detail.get("basic_info")) or {}
    explicit_match_type, match_type = _extract_match_type(detail)
    map_value = _first_mapping_value((detail, basic_info), ("map", "map_name"))
    duration_value = _first_mapping_value((detail, basic_info), ("duration", "fight_seconds"))
    return {
        "active": active,
        "invalid_reason": invalid_reason,
        "match_id": match_id,
        "match_time": extract_match_time(outer),
        "map": str(map_value or ""),
        "duration": _optional_display_int(duration_value),
        "match_type": match_type if explicit_match_type else None,
        "team1": _source_team_summary(_mapping(detail.get("team1"))),
        "team2": _source_team_summary(_mapping(detail.get("team2"))),
    }


def _tombstone(
    match_id: int,
    payload: Mapping[str, Any],
    detail: Mapping[str, Any],
    schema_version: int,
    reason: str,
) -> Dict[str, Any]:
    fact: Dict[str, Any] = {
        "match_id": match_id,
        "active": False,
        "invalid_reason": reason,
        "schema_version": schema_version,
        "source_cached_at": _source_cached_at(payload),
    }
    fact["source_hash"] = build_source_hash(
        _source_summary(match_id, payload, detail, False, reason)
    )
    return fact


def _unavailable(*mappings: Mapping[str, Any]) -> bool:
    return any(mapping.get("unavailable") is True for mapping in mappings)


def build_match_fact(match_id: Any, payload: Dict[str, Any], schema_version: int) -> Dict[str, Any]:
    """Build an active 3v3 fact or an inactive tombstone for a valid match ID.

    Missing player scores remain queryable as an active, score-incomplete fact.
    Structural failure deliberately produces a tombstone so a later old source
    cannot resurrect an already invalidated match.
    """
    normalized_match_id = normalize_positive_int(match_id)
    if normalized_match_id is None:
        raise ValueError("match_id must be a positive integer")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version <= 0:
        raise ValueError("schema_version must be a positive integer")
    if not isinstance(payload, Mapping):
        return _tombstone(normalized_match_id, {}, {}, schema_version, "invalid_payload")

    outer, envelope, detail = _detail_parts(payload)
    if _unavailable(outer, envelope, detail):
        return _tombstone(normalized_match_id, outer, detail, schema_version, "unavailable")

    explicit_match_type, match_type = _extract_match_type(detail)
    if explicit_match_type and match_type != 3:
        return _tombstone(normalized_match_id, outer, detail, schema_version, "not_3v3")

    match_time = extract_match_time(outer)
    if match_time is None:
        return _tombstone(normalized_match_id, outer, detail, schema_version, "missing_match_time")

    team1_raw = _mapping(detail.get("team1"))
    team2_raw = _mapping(detail.get("team2"))
    if team1_raw is None or team2_raw is None:
        return _tombstone(normalized_match_id, outer, detail, schema_version, "invalid_team_structure")
    team1 = _team_fact(team1_raw)
    team2 = _team_fact(team2_raw)
    if team1 is None or team2 is None:
        return _tombstone(normalized_match_id, outer, detail, schema_version, "invalid_team_structure")
    if team1["won"] == team2["won"]:
        return _tombstone(normalized_match_id, outer, detail, schema_version, "invalid_winner")

    basic_info = _mapping(detail.get("basic_info")) or {}
    map_value = _first_mapping_value((detail, basic_info), ("map", "map_name"))
    duration_value = _first_mapping_value((detail, basic_info), ("duration", "fight_seconds"))
    fact = {
        "match_id": normalized_match_id,
        "active": True,
        "invalid_reason": None,
        "match_time": match_time,
        "map": str(map_value or ""),
        "duration": _optional_display_int(duration_value),
        "match_type": 3 if match_type is None else match_type,
        "schema_version": schema_version,
        "source_cached_at": _source_cached_at(outer),
        "team1": team1,
        "team2": team2,
        "any_team_combo_keys": sorted(set(team1["combo_keys"]).union(team2["combo_keys"])),
        "min_team_score_sum": min(team1["score_sum"], team2["score_sum"])
        if team1["score_complete"] and team2["score_complete"]
        else None,
        "max_team_score_sum": max(team1["score_sum"], team2["score_sum"])
        if team1["score_complete"] and team2["score_complete"]
        else None,
    }
    fact["source_hash"] = build_source_hash(
        _source_summary(normalized_match_id, outer, detail, True, None)
    )
    return fact
