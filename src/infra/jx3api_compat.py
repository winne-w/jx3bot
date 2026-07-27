from __future__ import annotations

import copy
import time
from typing import Any
from urllib.parse import urlsplit


def normalize_jx3api_response(url: str, response: dict[str, Any]) -> dict[str, Any]:
    """Project JX3API response fields onto the legacy consumer contract."""
    if not isinstance(response, dict):
        return response

    normalized = copy.deepcopy(response)
    path = urlsplit(url).path.rstrip("/")
    data = normalized.get("data")

    if path == "/firework/records" and isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                item.setdefault("receive", item.get("receiver", ""))
                item.setdefault("map_name", item.get("mapName", ""))
                item.setdefault("name", item.get("firework", ""))
    elif path == "/monster/records" and isinstance(data, dict):
        data.setdefault("zoneName", data.get("zone", ""))
        data.setdefault("serverName", data.get("server", ""))
        data.setdefault("globalRoleId", data.get("globalId", ""))
        data.setdefault("gameEnergy", data.get("skillEnergy", 0))
        data.setdefault("gameStamina", data.get("skillStamina", 0))
    elif path == "/exam/search" and isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                item.setdefault("id", item.get("index", "未知ID"))
    elif path == "/fraud/detail" and isinstance(data, list):
        normalized["data"] = [_normalize_fraud_item(item) for item in data if isinstance(item, dict)]
    elif path == "/active/calendar" and isinstance(data, dict):
        data.setdefault("luck", data.get("lucky", []))
        weekly = data.get("weekly")
        if isinstance(weekly, dict):
            data.setdefault("team", list(weekly.get("conn") or []) + list(weekly.get("raid") or []))
    elif path == "/server/status/check":
        _normalize_status_data(data)

    return normalized


def _normalize_fraud_item(item: dict[str, Any]) -> dict[str, Any]:
    if isinstance(item.get("data"), list):
        return item

    pid = item.get("pid")
    url = "https://tieba.baidu.com/p/{}".format(pid) if pid else ""
    return {
        "server": item.get("server", ""),
        "tieba": item.get("tieba", ""),
        "data": [
            {
                "title": item.get("title", ""),
                "url": url,
                "text": item.get("content", ""),
                "time": item.get("created", 0),
            }
        ],
    }


def _normalize_status_data(data: Any) -> None:
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    sampled_at = int(time.time())
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_status = item.get("status")
        if isinstance(raw_status, str):
            item["legacyStatus"] = 0 if raw_status == "维护" else 1
        elif isinstance(raw_status, int):
            item.setdefault("legacyStatus", raw_status)
        item.setdefault("time", sampled_at)
