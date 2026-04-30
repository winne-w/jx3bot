import hashlib
import json
from typing import Any, Dict, List


def normalize_equipment_snapshot(armors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort armors by pos, ui_id, name. Returns a new list, does not modify input."""
    return sorted(armors, key=lambda item: (
        item.get("pos"),
        item.get("ui_id"),
        item.get("name"),
    ))


def normalize_talent_snapshot(talents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort talents by level, id (or talent_id), name. Returns a new list, does not modify input."""
    return sorted(talents, key=lambda item: (
        item.get("level"),
        item.get("id", item.get("talent_id")),
        item.get("name"),
    ))


def calculate_snapshot_hash(items: List[Dict[str, Any]]) -> str:
    """Serialize items with canonical JSON and return SHA-256 hex digest."""
    payload = json.dumps(
        items,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_equipment_snapshot(armors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an equipment snapshot dict with normalized armors and content hash."""
    normalized = normalize_equipment_snapshot(armors)
    return {
        "snapshot_hash": calculate_snapshot_hash(normalized),
        "armors": normalized,
        "schema_version": 1,
    }


def build_talent_snapshot(talents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a talent snapshot dict with normalized talents and content hash."""
    normalized = normalize_talent_snapshot(talents)
    return {
        "snapshot_hash": calculate_snapshot_hash(normalized),
        "talents": normalized,
        "schema_version": 1,
    }
