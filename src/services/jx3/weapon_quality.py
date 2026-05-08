from __future__ import annotations

from typing import Any, Optional

import config


def is_jjc_legendary_weapon(weapon_quality: Any, weapon_name: Optional[str] = None) -> bool:
    """A weapon is legendary only when quality is '5' AND name is in the allowlist.
    """
    if str(weapon_quality) != "5":
        return False
    if not weapon_name:
        return False
    return weapon_name in config.JJC_LEGENDARY_WEAPON_NAMES


def extract_weapon_name(weapon: Any) -> Optional[str]:
    if not isinstance(weapon, dict):
        return None
    weapon_name = weapon.get("name")
    if not weapon_name:
        return None
    return str(weapon_name)


def extract_member_weapon_name(member: Any) -> Optional[str]:
    if not isinstance(member, dict):
        return None
    weapon_name = member.get("weapon_name")
    if weapon_name:
        return str(weapon_name)
    return extract_weapon_name(member.get("weapon"))
