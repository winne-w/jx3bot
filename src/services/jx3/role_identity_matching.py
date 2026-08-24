from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


IDENTITY_LEVEL_GLOBAL_ID = "global_id"
IDENTITY_LEVEL_GLOBAL_ROLE = "global"
IDENTITY_LEVEL_GAME_ROLE = "game_role"
IDENTITY_LEVEL_NAME = "name"

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

    Replay usually provides role_name as "name·server". If the separator is
    absent, the optional server argument is used as the server value.
    """
    raw_name = str(role_name or "").strip()
    raw_server = str(server or "").strip()
    if "·" in raw_name:
        name_part, server_part = raw_name.rsplit("·", 1)
        return server_part.strip(), name_part.strip()
    return raw_server, raw_name


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
        zone = clean_id(raw.get("zone")) or server_zone_map.get(server) or server_zone_map.get(normalize_text(server))
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
