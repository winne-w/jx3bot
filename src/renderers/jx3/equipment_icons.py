"""Prepare embedded icons so equipment screenshots do not depend on browser downloads."""
import copy
from typing import Any, Dict

from src.infra.jx3box_icons import fetch_icon_data_uris


async def prepare_equipment_icons(context: Dict[str, Any]) -> Dict[str, Any]:
    prepared = copy.deepcopy(context)
    icons = []
    for row in prepared.get("equipment", []):
        for key in ("icon", "color_stone_icon"):
            if isinstance(row.get(key), dict):
                icons.append(row[key])
        for key in ("stone_icons", "enchant_icons"):
            icons.extend(icon for icon in row.get(key, []) if isinstance(icon, dict))
    loaded = await fetch_icon_data_uris(icon.get("url", "") for icon in icons)
    for icon in icons:
        icon["image_src"] = loaded.get(icon.get("url"), "")
    return prepared
