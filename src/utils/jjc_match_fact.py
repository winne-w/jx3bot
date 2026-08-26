"""Dependency-neutral primitives shared by JJC match-fact layers."""

import math
import re
from typing import Any, List, Optional


_CANONICAL_POSITIVE_INT = re.compile(r"[1-9][0-9]*\Z")


def normalize_positive_int(value: Any) -> Optional[int]:
    """Return a positive integer only for exact, non-boolean representations."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        integer_value = int(value)
        return integer_value if integer_value > 0 else None
    if isinstance(value, str) and _CANONICAL_POSITIVE_INT.fullmatch(value):
        return int(value)
    return None


def encode_combo_key(kungfu_ids: List[int]) -> str:
    """Encode a non-empty kungfu multiset in its stable v1 representation."""
    normalized: List[int] = []
    for value in kungfu_ids:
        kungfu_id = normalize_positive_int(value)
        if kungfu_id is None:
            raise ValueError("kungfu_ids must contain positive integers")
        normalized.append(kungfu_id)
    if not normalized:
        raise ValueError("kungfu_ids must not be empty")
    normalized.sort()
    return "v1:%d:%s" % (len(normalized), ",".join(str(item) for item in normalized))
