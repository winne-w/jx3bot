"""Pure domain rules for JX3 role identity keys, replay matching, and guards."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.domain.role_name import split_display_name, strip_server_suffix


IDENTITY_LEVEL_GLOBAL_ID = "global_id"
IDENTITY_LEVEL_GLOBAL_ROLE = "global"
IDENTITY_LEVEL_GAME_ROLE = "game_role"
IDENTITY_LEVEL_NAME = "name"
STRICT_QUERY_ID_REFRESH_SOURCE = "indicator_replay_verified"


def has_verified_query_ids(existing: Dict[str, Any]) -> bool:
    return (
        existing.get("global_role_id_refresh_source") == STRICT_QUERY_ID_REFRESH_SOURCE
        and isinstance(existing.get("global_role_id_refreshed_at"), datetime)
    )


PROFILE_GUARDED_FIELDS = (
    "server",
    "normalized_server",
    "name",
    "normalized_name",
    "zone",
    "role_id",
    "game_role_id",
    "global_role_id",
    "person_id",
)


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def clean_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def coerce_match_time(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return None


def observed_match_time_from_doc(doc: Dict[str, Any]) -> Optional[int]:
    observed = coerce_match_time(doc.get("role_info_observed_match_time"))
    if observed is not None:
        return observed
    return coerce_match_time(doc.get("profile_observed_at"))


def should_overwrite_profile_fields(
    existing: Dict[str, Any],
    observed_match_time: Optional[int] = None,
    force_profile_update: bool = False,
) -> bool:
    if has_verified_query_ids(existing):
        return False
    if force_profile_update:
        return True
    if observed_match_time is None:
        return False
    existing_observed = observed_match_time_from_doc(existing)
    return existing_observed is None or observed_match_time > existing_observed


def build_guarded_profile_set_fields(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
    observed_match_time: Optional[int] = None,
    force_profile_update: bool = False,
) -> Dict[str, Any]:
    """Return profile fields that may be written under the match-time guard.

    Newer observed matches may replace current profile fields. Older or
    unobserved sources may only fill fields that are currently missing.
    """
    allow_overwrite = should_overwrite_profile_fields(
        existing,
        observed_match_time=observed_match_time,
        force_profile_update=force_profile_update,
    )
    if has_verified_query_ids(existing):
        for field_name in PROFILE_GUARDED_FIELDS:
            value = incoming.get(field_name)
            if value is not None and value != "" and value != existing.get(field_name):
                return {}
    set_fields: Dict[str, Any] = {}
    for field_name in PROFILE_GUARDED_FIELDS:
        value = incoming.get(field_name)
        if value is None or value == "":
            continue
        if allow_overwrite or not clean_id(existing.get(field_name)):
            set_fields[field_name] = value
    return set_fields


def split_replay_role_name(role_name: Any, server: Any = "") -> Tuple[str, str]:
    """Parse replay role_name into (server, name).

    Delegates to `src.domain.role_name.split_display_name` so names containing
    '·' are protected when an explicit server is provided, and legacy
    `"name·server"` replay values split on the last `·`.
    """
    return split_display_name(role_name, server)


def classify_replay_player_match(
    player: Dict[str, Any],
    *,
    role_id: Optional[str] = None,
    role_name: Optional[str] = None,
    server: Optional[str] = None,
) -> Optional[str]:
    """Classify whether a replay player matches a target role.

    Returns:
    - None if both `role_id` and `replay_role_id` are non-empty and unequal
      (never falls back to name-only matching when explicit role IDs conflict).
    - "strong" if `role_id` matches `replay_role_id` with no name/server conflict.
    - "weak_name_only" if either side lacks `role_id`, `role_name` matches, and
      `server` has no conflict.
    - None otherwise.
    """
    if not isinstance(player, dict):
        return None

    target_role_id = clean_id(role_id)
    target_server = clean_id(server)
    target_name = clean_id(role_name)
    if target_name and target_server:
        target_name = strip_server_suffix(target_name, target_server)

    replay_role_id = clean_id(player.get("role_id")) or clean_id(player.get("roleId"))
    if target_role_id and replay_role_id and target_role_id != replay_role_id:
        return None

    raw_player_server = clean_id(player.get("server")) or ""
    raw_role_name = clean_id(player.get("role_name")) or clean_id(player.get("roleName")) or ""
    if raw_player_server:
        replay_server_raw, replay_name_raw = split_display_name(raw_role_name, raw_player_server)
    elif target_name and raw_role_name == target_name:
        replay_server_raw, replay_name_raw = "", raw_role_name
    else:
        replay_server_raw, replay_name_raw = split_display_name(raw_role_name, "")

    replay_server = clean_id(replay_server_raw)
    player_name = (
        clean_id(replay_name_raw)
        or clean_id(player.get("person_name"))
        or clean_id(player.get("name"))
    )

    if target_role_id and replay_role_id == target_role_id:
        if target_name and player_name and player_name != target_name:
            return None
        if target_server and replay_server and replay_server != target_server:
            return None
        return "strong"

    if not target_name or not player_name or player_name != target_name:
        return None
    if target_server and replay_server and replay_server != target_server:
        return None
    return "weak_name_only"


def build_identity_key(
    global_role_id: Optional[str] = None,
    zone: Optional[str] = None,
    game_role_id: Optional[str] = None,
    server: Optional[str] = None,
    name: Optional[str] = None,
    global_id: Optional[str] = None,
) -> Tuple[str, str]:
    """Build the preferred identity key with global_id as the strongest ID."""
    gid = clean_id(global_id)
    if gid:
        return "global_id:%s" % gid, IDENTITY_LEVEL_GLOBAL_ID

    sk01 = clean_id(global_role_id)
    if sk01:
        return "global:%s" % sk01, IDENTITY_LEVEL_GLOBAL_ROLE

    z = clean_id(zone)
    rid = clean_id(game_role_id)
    if z and rid:
        return "game:%s:%s" % (z, rid), IDENTITY_LEVEL_GAME_ROLE

    return "name:%s:%s" % (normalize_text(server), normalize_text(name)), IDENTITY_LEVEL_NAME


def legacy_identity_keys(
    global_role_id: Optional[str] = None,
    zone: Optional[str] = None,
    game_role_id: Optional[str] = None,
    server: Optional[str] = None,
    name: Optional[str] = None,
) -> List[str]:
    keys: List[str] = []
    sk01 = clean_id(global_role_id)
    if sk01:
        keys.append("global:%s" % sk01)
    z = clean_id(zone)
    rid = clean_id(game_role_id)
    if z and rid:
        keys.append("game:%s:%s" % (z, rid))
    ns = normalize_text(server)
    nn = normalize_text(name)
    if ns or nn:
        keys.append("name:%s:%s" % (ns, nn))
    return keys


def extract_replay_players(
    replay_data: Dict[str, Any],
    server_zone_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Extract normalized player identities from a match replay payload."""
    data = replay_data.get("data") if isinstance(replay_data, dict) else None
    players_raw: Any = []
    if isinstance(data, dict):
        players_raw = data.get("players") or []
    elif isinstance(data, list):
        players_raw = data

    server_zone_map = server_zone_map or {}
    players: List[Dict[str, Any]] = []
    for raw in players_raw:
        if not isinstance(raw, dict):
            continue
        server, name = split_replay_role_name(raw.get("role_name"), raw.get("server"))
        zone = (
            clean_id(raw.get("zone"))
            or server_zone_map.get(server)
            or server_zone_map.get(normalize_text(server))
        )
        players.append({
            "global_id": clean_id(raw.get("global_role_id")),
            "role_id": clean_id(raw.get("role_id")),
            "server": server,
            "name": name,
            "zone": zone,
            "kungfu_id": clean_id(raw.get("kungfu_id")),
            "kungfu_name": clean_id(raw.get("kungfu_name")),
            "team": raw.get("team"),
            "raw": raw,
        })
    return players


def parse_indicator_identity(indicator_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    data = indicator_data.get("data") if isinstance(indicator_data, dict) else None
    if not isinstance(data, dict):
        data = indicator_data
    role_info = data.get("role_info") if isinstance(data, dict) else None
    person_info = data.get("person_info") if isinstance(data, dict) else None
    if not isinstance(role_info, dict):
        role_info = {}
    if not isinstance(person_info, dict):
        person_info = {}

    global_role_id = clean_id(role_info.get("global_role_id"))
    if global_role_id and not global_role_id.startswith("SK01-"):
        global_role_id = None

    return {
        "global_role_id": global_role_id,
        "role_id": clean_id(role_info.get("role_id")),
        "game_role_id": clean_id(role_info.get("role_id")),
        "zone": clean_id(role_info.get("zone")),
        "server": clean_id(role_info.get("server")),
        "name": clean_id(role_info.get("name")),
        "person_id": clean_id(person_info.get("person_id")),
    }


def _coerce_indicator_int(value: Any) -> Optional[int]:
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


def _find_3v3_metrics(indicator: Dict[str, Any]) -> List[Dict[str, Any]]:
    metrics = indicator.get("metrics") or []
    if not isinstance(metrics, list):
        return []
    result: List[Dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        pvp_type = _coerce_indicator_int(
            metric.get("pvp_type") or metric.get("pvpType") or metric.get("type")
        )
        if pvp_type is None or pvp_type == 3:
            result.append(metric)
    return result


def _has_valid_3v3_indicator(raw: Dict[str, Any]) -> bool:
    """Pure equivalent of checking `not parse_3v3_indicator(raw).get('error')`."""
    data = raw.get("data")
    if not isinstance(data, dict):
        return False
    indicators = data.get("indicator") or []
    if not isinstance(indicators, list):
        return False

    target: Optional[Dict[str, Any]] = None
    for indicator in indicators:
        if not isinstance(indicator, dict):
            continue
        indicator_type = str(indicator.get("type") or "")
        if indicator_type in {"3c", "3d"} or _find_3v3_metrics(indicator):
            target = indicator
            break
    if target is None:
        return False

    performance = target.get("performance")
    if not isinstance(performance, dict):
        performance = {}
    metrics = _find_3v3_metrics(target)
    metric_3v3: Dict[str, Any] = next(
        (
            item
            for item in metrics
            if isinstance(item, dict)
            and (
                _coerce_indicator_int(
                    item.get("pvp_type") or item.get("pvpType") or item.get("type")
                )
                in (None, 3)
            )
            and (
                item.get("total_count") is not None
                or item.get("win_count") is not None
                or item.get("level") is not None
                or item.get("total") is not None
                or item.get("best_count") is not None
                or item.get("bestCount") is not None
                or item.get("mvp_count") is not None
                or item.get("mvpCount") is not None
            )
        ),
        {},
    )

    total_matches = _coerce_indicator_int(
        target.get("total_matches")
        or target.get("total_count")
        or target.get("total")
        or target.get("match_count")
        or performance.get("total_count")
        or performance.get("total")
        or performance.get("match_count")
        or metric_3v3.get("total_count")
        or metric_3v3.get("total")
        or metric_3v3.get("match_count")
    )
    score = _coerce_indicator_int(
        target.get("score")
        or target.get("rating")
        or target.get("mmr")
        or target.get("current_score")
        or performance.get("score")
        or performance.get("rating")
        or performance.get("mmr")
        or performance.get("current_score")
        or metric_3v3.get("score")
        or metric_3v3.get("rating")
        or metric_3v3.get("mmr")
    )
    grade = _coerce_indicator_int(
        target.get("grade")
        or target.get("rank")
        or target.get("segment")
        or target.get("level")
        or performance.get("grade")
        or performance.get("rank")
        or performance.get("segment")
        or performance.get("level")
        or metric_3v3.get("grade")
        or metric_3v3.get("rank")
        or metric_3v3.get("segment")
        or metric_3v3.get("level")
    )
    return not (total_matches is None and score is None and grade is None)


def validate_query_id_evidence(
    existing: Dict[str, Any],
    *,
    request_zone: str,
    request_server: str,
    request_role_id: str,
    indicator_data: Dict[str, Any],
    replay_data: Dict[str, Any],
) -> bool:
    """Validate original upstream responses, not cached identity wrappers."""
    numeric_id = clean_id(existing.get("global_id"))
    sk01 = clean_id(existing.get("global_role_id"))
    if not numeric_id or not numeric_id.isdigit() or not sk01 or not sk01.startswith("SK01-"):
        return False
    if not all(clean_id(value) for value in (request_zone, request_server, request_role_id)):
        return False
    if request_zone != existing.get("zone") or request_server != existing.get("server"):
        return False
    if (
        not isinstance(indicator_data, dict)
        or type(indicator_data.get("code")) is not int
        or indicator_data.get("code") != 0
    ):
        return False
    if (
        not isinstance(replay_data, dict)
        or type(replay_data.get("code")) is not int
        or replay_data.get("code") != 0
    ):
        return False
    identity = parse_indicator_identity(indicator_data)
    if (
        identity.get("role_id") != str(request_role_id)
        or identity.get("zone") != request_zone
        or identity.get("server") != request_server
        or identity.get("global_role_id") != sk01
        or identity.get("name") != existing.get("name")
    ):
        return False
    if not _has_valid_3v3_indicator(indicator_data):
        return False
    players = extract_replay_players(replay_data)
    target = [player for player in players if player.get("global_id") == numeric_id]
    if not target or any(player.get("role_id") != str(request_role_id) for player in target):
        return False
    return all(
        player.get("global_id") == numeric_id
        for player in players
        if player.get("role_id") == str(request_role_id)
    )


def build_profile_history_entry(
    server: Optional[str] = None,
    name: Optional[str] = None,
    zone: Optional[str] = None,
    role_id: Optional[str] = None,
    game_role_id: Optional[str] = None,
    global_role_id: Optional[str] = None,
    global_id: Optional[str] = None,
    person_id: Optional[str] = None,
    match_id: Optional[Any] = None,
    match_time: Optional[Any] = None,
    source: Optional[str] = None,
    observed_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "server": server,
        "name": name,
        "zone": zone,
        "role_id": role_id or game_role_id,
        "game_role_id": game_role_id or role_id,
        "global_role_id": global_role_id,
        "global_id": global_id,
        "person_id": person_id,
        "match_id": clean_id(match_id),
        "match_time": match_time,
        "source": source,
        "observed_at": observed_at or datetime.now(timezone.utc),
    }
    return {key: value for key, value in entry.items() if value is not None and value != ""}


def _profile_history_fingerprint(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        clean_id(entry.get("global_id")),
        clean_id(entry.get("global_role_id")),
        clean_id(entry.get("zone")),
        clean_id(entry.get("role_id") or entry.get("game_role_id")),
        normalize_text(entry.get("server")),
        normalize_text(entry.get("name")),
        clean_id(entry.get("person_id")),
        clean_id(entry.get("match_id")),
        entry.get("match_time"),
        clean_id(entry.get("source")),
    )


def merge_profile_history(
    existing: Optional[Sequence[Dict[str, Any]]],
    additions: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for entry in list(existing or []) + list(additions):
        if not isinstance(entry, dict):
            continue
        fingerprint = _profile_history_fingerprint(entry)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged.append(dict(entry))
    return merged


def classify_identity_conflicts(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classify contradictory identity mappings without deciding repair action."""
    rows = [row for row in records if isinstance(row, dict)]
    conflicts: List[Dict[str, Any]] = []
    conflicts.extend(_classify_many_to_many(rows, "global_id", "role_id", "global_id_conflict"))
    conflicts.extend(_classify_many_to_many(rows, "global_role_id", "global_id", "global_role_id_global_id_conflict"))
    conflicts.extend(_classify_many_to_many(rows, "role_zone_key", "global_id", "role_id_global_id_conflict"))
    conflicts.extend(_classify_many_to_many(rows, "global_id", "person_id", "person_id_conflict"))
    return conflicts


def classify_profile_change(existing: Dict[str, Any], incoming: Dict[str, Any]) -> List[str]:
    changed: List[str] = []
    for field_name in ("server", "name", "zone", "role_id", "game_role_id", "global_role_id", "person_id"):
        old_value = clean_id(existing.get(field_name))
        new_value = clean_id(incoming.get(field_name))
        if old_value and new_value and old_value != new_value:
            changed.append(field_name)
    return changed


def _classify_many_to_many(
    rows: List[Dict[str, Any]],
    left_field: str,
    right_field: str,
    conflict_type: str,
) -> List[Dict[str, Any]]:
    grouped: Dict[str, set] = {}
    for row in rows:
        left_value = _field_value(row, left_field)
        right_value = _field_value(row, right_field)
        if not left_value or not right_value:
            continue
        grouped.setdefault(left_value, set()).add(right_value)

    conflicts: List[Dict[str, Any]] = []
    for left_value, right_values in grouped.items():
        if len(right_values) > 1:
            conflicts.append({
                "type": conflict_type,
                "key": left_value,
                "values": sorted(right_values),
            })
    return conflicts


def _field_value(row: Dict[str, Any], field_name: str) -> Optional[str]:
    if field_name == "role_zone_key":
        zone = clean_id(row.get("zone"))
        role_id = clean_id(row.get("role_id") or row.get("game_role_id"))
        if zone and role_id:
            return "%s:%s" % (zone, role_id)
        return None
    return clean_id(row.get(field_name))


__all__ = [
    "IDENTITY_LEVEL_GAME_ROLE",
    "IDENTITY_LEVEL_GLOBAL_ID",
    "IDENTITY_LEVEL_GLOBAL_ROLE",
    "IDENTITY_LEVEL_NAME",
    "PROFILE_GUARDED_FIELDS",
    "STRICT_QUERY_ID_REFRESH_SOURCE",
    "build_guarded_profile_set_fields",
    "build_identity_key",
    "build_profile_history_entry",
    "classify_identity_conflicts",
    "classify_profile_change",
    "classify_replay_player_match",
    "clean_id",
    "coerce_match_time",
    "extract_replay_players",
    "has_verified_query_ids",
    "legacy_identity_keys",
    "merge_profile_history",
    "normalize_text",
    "observed_match_time_from_doc",
    "parse_indicator_identity",
    "should_overwrite_profile_fields",
    "split_replay_role_name",
    "validate_query_id_evidence",
]
