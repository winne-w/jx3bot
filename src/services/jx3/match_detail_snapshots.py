"""Compatibility re-export of pure match-detail snapshot domain rules."""
from __future__ import annotations

from src.domain.snapshots import *  # noqa: F401, F403
from src.domain.snapshots import (  # noqa: F401
    TALENT_SNAPSHOT_SCHEMA_VERSION,
    build_equipment_snapshot,
    build_talent_snapshot,
    calculate_snapshot_hash,
    normalize_equipment_snapshot,
    normalize_talent_snapshot,
)

__all__ = [
    "TALENT_SNAPSHOT_SCHEMA_VERSION",
    "build_equipment_snapshot",
    "build_talent_snapshot",
    "calculate_snapshot_hash",
    "normalize_equipment_snapshot",
    "normalize_talent_snapshot",
]
