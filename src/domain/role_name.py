"""Pure domain rules for parsing and normalizing JX3 role display names."""
from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple


def strip_server_suffix(name: Any, server: Any = "") -> str:
    """Strip trailing '·<server>' suffix only when it matches the explicit server.

    Protects role names containing '·' themselves:
    - strip_server_suffix("星·辰·梦江南", "梦江南") -> "星·辰"
    - strip_server_suffix("星·辰·梦江南", "蝶恋花") -> "星·辰·梦江南"
    - strip_server_suffix("星·辰", "梦江南") -> "星·辰"
    """
    raw_name = str(name or "").strip()
    raw_server = str(server or "").strip()
    if not raw_name or not raw_server or "·" not in raw_name:
        return raw_name

    left, right = raw_name.rsplit("·", 1)
    left = left.strip()
    right = right.strip()
    if left and right == raw_server:
        return left
    return raw_name


def split_display_name(
    role_name: Any,
    server: Any = "",
    known_servers: Optional[Iterable[str]] = None,
) -> Tuple[str, str]:
    """Split a display role name into `(server, name)`.

    Rules:
    - When `server` is non-empty, strip `"·" + server` only if `role_name` ends
      with that server suffix; otherwise preserve `role_name` intact so names
      containing `·` are not mis-split.
    - When `server` is empty and `role_name` contains `·`, split on the last
      `·` (`rsplit("·", 1)`). If `known_servers` is provided, only treat the
      trailing segment as a server when it is in `known_servers`.
    """
    raw_name = str(role_name or "").strip()
    raw_server = str(server or "").strip()
    if raw_server:
        return raw_server, strip_server_suffix(raw_name, raw_server)

    if not raw_name or "·" not in raw_name:
        return "", raw_name

    name_part, server_part = raw_name.rsplit("·", 1)
    parsed_name = name_part.strip()
    parsed_server = server_part.strip()
    if known_servers is not None:
        known = {str(item).strip() for item in known_servers if str(item or "").strip()}
        if parsed_server not in known:
            return "", raw_name
    return parsed_server, parsed_name


__all__ = [
    "split_display_name",
    "strip_server_suffix",
]
