"""Pure mobile equipment presentation rules; never derive rates from ratings."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from src.services.jx3.jjc_kungfu_meta import get_jjc_kungfu_catalog


_KUNGFU_CATEGORIES = {row["name"]: row["category"] for row in get_jjc_kungfu_catalog()}
_RATE_NAMES = {
    "会心": ("会心等级", "会心", "会心率"),
    "会效": ("会心效果等级", "会心效果", "会效"),
    "加速": ("加速等级", "加速"),
    "破防": ("破防等级", "破防"),
    "无双": ("无双等级", "无双"),
    "外防": ("外功防御", "外功防御等级", "外防"),
    "内防": ("内功防御", "内功防御等级", "内防"),
    "御劲": ("御劲等级", "御劲"),
    "化劲": ("化劲等级", "化劲"),
}
_NAMES = {
    "基础攻击": ("基础攻击", "基础攻击力", "内功攻击", "外功攻击", "攻击力"),
    "面板攻击": ("面板攻击", "面板攻击力", "攻击"),
    "基础治疗": ("基础治疗", "基础治疗量"),
    "面板治疗": ("面板治疗", "面板治疗量", "治疗量"),
    "气血": ("气血", "最大气血", "气血上限"),
    "根骨": ("根骨",), "破招": ("破招", "破招值", "破招等级"),
}


def _number(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip().rstrip("%"))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _format(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    return format(number, "f").rstrip("0").rstrip(".") if number != number.to_integral() else str(int(number))


def build_core_stats(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.get("panelList")
    if isinstance(raw, dict):
        raw = raw.get("panel")
    rows = {str(row.get("name") or ""): row for row in raw if isinstance(row, dict)} if isinstance(raw, list) else {}
    category = _KUNGFU_CATEGORIES.get(str(payload.get("kungfuName") or ""))
    role_type = str(payload.get("kungfuType") or "").strip().lower()
    if category == "healer":
        healing = True
    elif category in {"dps", "tank"} or role_type in {"dps", "tank", "输出", "攻击", "防御"}:
        healing = False
    elif role_type in {"hps", "治疗", "奶", "heal", "healer"}:
        healing = True
    else:
        healing_value = max((_number(rows.get(name, {}).get("value")) or Decimal(0))
                            for name in _NAMES["基础治疗"] + _NAMES["面板治疗"])
        attack_value = max((_number(rows.get(name, {}).get("value")) or Decimal(0))
                           for name in _NAMES["基础攻击"] + _NAMES["面板攻击"])
        healing = healing_value > 0 and healing_value > attack_value
    pvp = str(payload.get("equipType") or "").lower() in {"竞技对抗", "pvp"}
    if healing:
        keys = ["装分", "基础治疗", "面板治疗", "会心", "会效", "加速", "气血", "根骨", "外防", "内防", "御劲", "化劲"]
    elif pvp:
        keys = ["装分", "基础攻击", "面板攻击", "会心", "会效", "加速", "破防", "气血", "外防", "内防", "御劲", "化劲"]
    else:
        keys = ["装分", "基础攻击", "面板攻击", "会心", "会效", "加速", "破防", "破招", "无双", "气血", "外防", "内防"]
    cards = []
    for key in keys:
        if key == "装分":
            score = payload.get("equipScore")
            if score is None and isinstance(payload.get("panelList"), dict):
                score = payload["panelList"].get("score")
            cards.append({"name": key, "value": _format(score)})
            continue
        aliases = _RATE_NAMES.get(key, _NAMES.get(key, (key,)))
        row = next((rows[name] for name in aliases if name in rows), {})
        if key in _RATE_NAMES and key != "加速" and _number(row.get("percent")) is not None:
            cards.append({"name": key, "value": _format(row["percent"]) + "%"})
        else:
            # A rating remains a rating when the API does not supply a rate.
            label = str(row.get("name") or key) if key in _RATE_NAMES and key != "加速" else key
            cards.append({"name": label, "value": _format(row.get("value"))})
    return cards


def compact_attribute_names(attributes: Any) -> list[str]:
    names = []
    reverse = {alias: short for short, aliases in _RATE_NAMES.items() for alias in aliases}
    for row in attributes if isinstance(attributes, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or "武器伤害" in name or name in {"体质", "基础攻击", "基础攻击力", "最小攻击", "最大攻击", "武器最小伤害", "武器最大伤害"}:
            continue
        short = "治疗" if "治疗" in name else reverse.get(name, name)
        if short.endswith("等级"):
            short = short[:-2]
        elif short.endswith("值"):
            short = short[:-1]
        if short not in names:
            names.append(short)
    primary_names = {"根骨", "元气", "力道", "身法"}
    return sorted(names, key=lambda name: name not in primary_names)[:5]


def refinement_view(strength: Any, maximum: Any) -> dict[str, str]:
    def integer(value):
        if type(value) is int:
            return value
        if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 2:
            return int(value)
        return None
    current, limit = integer(strength), integer(maximum)
    if current is not None and limit is not None and 0 <= current <= limit <= 8 and limit > 0:
        return {"stars": "★" * current + "☆" * (limit-current), "text": f"精炼 {current}/{limit}"}
    current_text = str(current) if current is not None else "—"
    limit_text = str(limit) if limit is not None else "—"
    return {"stars": "", "text": f"精炼 {current_text}/{limit_text}"}
