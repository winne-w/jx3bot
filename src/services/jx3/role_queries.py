from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.infra.jx3api_online import fetch_role_online
from src.services.jx3.query_context import RenderSpec


_BEIJING = timezone(timedelta(hours=8))


def _collected_at(value: Any) -> str:
    if isinstance(value, bool):
        return "未提供"
    try:
        timestamp = float(value)
        if timestamp <= 0:
            return "未提供"
        return datetime.fromtimestamp(timestamp, _BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return "未提供"


def build_equipment_spec_or_text(
    *, data: dict[str, Any], server: str, role_name: str, random_text: str,
) -> tuple[Optional[RenderSpec], Optional[str]]:
    payload = data.get("data")
    if not isinstance(payload, dict):
        return None, "装备属性响应格式异常，请稍后重试"
    raw_equipment = payload.get("equipList")
    raw_panel = payload.get("panelList")
    if isinstance(raw_panel, dict):
        # Retain compatibility with previously collected panel payloads.
        raw_panel = raw_panel.get("panel")
    equipment = []
    for row in raw_equipment if isinstance(raw_equipment, list) else []:
        if not isinstance(row, dict):
            continue
        attributes = row.get("itemAttrib")
        stones = row.get("mountDiamond")
        color_stone = row.get("colorDiamond")
        enchants = []
        for key in ("minEnchant", "maxEnchant"):
            enchant = row.get(key)
            if isinstance(enchant, dict) and (enchant.get("itemName") or enchant.get("name")):
                enchants.append(str(enchant.get("itemName") or enchant.get("name")))
        equipment.append({
            "name": str(row.get("itemName") or row.get("name") or "未命名装备"),
            "level": row.get("itemLevel", row.get("quality", "—")),
            "type": str(row.get("itemType") or row.get("itemKind") or ""),
            "source": str(row.get("itemSource") or row.get("source") or ""),
            "strength": row.get("strengthLevel", "—"),
            "max_strength": row.get("maxStrengthLevel", "—"),
            "quality": row.get("itemQuality", "—"),
            "attributes": [{"name": str(value.get("name") or "属性"), "value": value.get("value", "—")}
                           for value in attributes if isinstance(value, dict)] if isinstance(attributes, list) else [],
            "stones": [str(value.get("itemName") or value.get("name") or "未命名五行石")
                       for value in stones if isinstance(value, dict)] if isinstance(stones, list) else [],
            "color_stone": str(color_stone.get("itemName") or color_stone.get("name") or "")
                           if isinstance(color_stone, dict) else "",
            "enchants": enchants,
        })
    panel = [{"name": str(row.get("name") or "属性"), "value": row.get("value", "—")}
             for row in raw_panel if isinstance(row, dict)] if isinstance(raw_panel, list) else []
    if not equipment and not panel:
        return None, f"未收录 {server}，{role_name} 的装备属性，请在游戏内更新装备资料后重试"
    legacy_panel = payload.get("panelList")
    score = payload.get("equipScore")
    if score is None and isinstance(legacy_panel, dict):
        score = legacy_panel.get("score")
    return RenderSpec(
        template_name="装备查询.html", width=1119, height="ck",
        context={"id": role_name, "qufu": server, "kungfu": str(payload.get("kungfuName") or "未提供"),
                 "score": score if score is not None else "—", "equipment": equipment, "panel": panel,
                 "collected_at": _collected_at(payload.get("cacheTime")), "text": random_text},
    ), None


def format_online_status(response: dict[str, Any], *, server: str, name: str) -> str:
    prefix = f"{server}，{name}："
    if not isinstance(response, dict):
        return prefix + "查询失败，在线状态响应格式异常"
    if response.get("error") or response.get("msg") != "success":
        return prefix + "查询失败，" + str(response.get("msg") or "在线状态接口暂不可用")
    rows = response.get("data")
    if not isinstance(rows, list):
        return prefix + "在线状态未知（接口未返回有效角色状态）"
    matches = [row for row in rows if isinstance(row, dict)
               and str(row.get("serverName") or "") == server
               and (str(row.get("roleName") or "") == name
                    or (name.isdigit() and str(row.get("roleId") or "") == name))]
    if len(matches) != 1:
        return prefix + "在线状态未知（未返回唯一匹配角色）"
    row = matches[0]
    online = row.get("onlineStatus")
    if type(online) is not bool:
        online = row.get("gameLogin")
    if type(online) is not bool:
        return prefix + "在线状态未知（接口未提供游戏登录状态）"
    return prefix + ("游戏在线" if online else "游戏离线")


async def query_online_status(*, url: str, server: str, name: str, token: str, ticket: str) -> str:
    response = await fetch_role_online(url=url, server=server, name=name, token=token, ticket=ticket)
    return format_online_status(response, server=server, name=name)
