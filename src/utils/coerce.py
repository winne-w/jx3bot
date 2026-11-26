"""Common pure type coercion, text normalization, and document helpers."""
from __future__ import annotations

import math
from typing import Any, Dict, Optional


def coerce_int(value: Any) -> Optional[int]:
    """Coerce an integer-like value to int.

    Rejects booleans and non-integer or non-finite floats. Accepts ints,
    integer-valued floats (e.g. 3.0), and numeric strings (e.g. "42", "3.0").
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            pass
        try:
            parsed = float(text)
        except ValueError:
            return None
        if not math.isfinite(parsed) or not parsed.is_integer():
            return None
        return int(parsed)
    return None


def coerce_float(value: Any) -> Optional[float]:
    """Coerce a finite numeric value to float, rejecting booleans."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def normalize_text(value: Any) -> str:
    """Return stripped lowercase string representation."""
    return str(value or "").strip().lower()


def clean_id(value: Any) -> Optional[str]:
    """Return stripped non-empty ID string, or None."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value or "").strip()
    return text or None


def pick_text(*values: Any) -> Optional[str]:
    """Return the first non-empty stripped string from values."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def strip_mongo_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a shallow copy of a MongoDB document without `_id`."""
    if doc is None:
        return None
    result = dict(doc)
    result.pop("_id", None)
    return result


__all__ = [
    "clean_id",
    "coerce_float",
    "coerce_int",
    "normalize_text",
    "pick_text",
    "strip_mongo_id",
]
