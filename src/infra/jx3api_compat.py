from __future__ import annotations

import copy
import time
from typing import Any
from urllib.parse import urlsplit
from datetime import datetime, timezone, timedelta


RESPONSE_TYPES = {
    "/firework/records": (list,), "/event/records": (list,),
    "/arena/recent": (dict,), "/card/record": (dict,),
    "/monster/records": (dict,), "/role/achievement": (dict,),
    "/active/calendar": (dict,), "/exam/search": (list,),
    "/fraud/detail": (dict, list), "/server/status/check": (dict, list),
    "/news/announce": (list,), "/news/records": (list,),
    "/skill/rework": (list,), "/calcd/attribute": (dict,),
    "/role/online/status": (list,),
}
_CST = timezone(timedelta(hours=8))


def is_jx3api_url(url: str) -> bool:
    return urlsplit(url).hostname in {"www.jx3api.com", "jx3api.com"}


def _timestamp(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return int(datetime.strptime(value, fmt).replace(tzinfo=_CST).timestamp())
            except ValueError:
                continue
    return 0


def normalize_jx3api_response(url: str, response: dict[str, Any]) -> dict[str, Any]:
    """Project JX3API response fields onto the legacy consumer contract."""
    if not isinstance(response, dict):
        return response

    normalized = copy.deepcopy(response)
    if not is_jx3api_url(url) or normalized.get("error"):
        return normalized
    path = urlsplit(url).path.rstrip("/")
    if is_jx3api_url(url) and path in RESPONSE_TYPES and "status" in normalized and not normalized.get("error"):
        status = normalized.get("status")
        detail = normalized.get("detail")
        expected = RESPONSE_TYPES[path]
        if detail == {} and expected == (list,):
            detail = []
        if (type(status) is int and status == 200 and isinstance(detail, expected)
                and (not isinstance(detail, list) or all(isinstance(row, dict) for row in detail))):
            normalized.update(code=200, msg="success", data=detail)
        elif type(status) is int and status != 200 and isinstance(detail, str):
            normalized.pop("data", None)
            normalized.update(
                code=status,
                msg=detail if detail and detail != "success" else "接口查询失败（状态码{}）".format(status),
                error="upstream_error",
            )
            return normalized
        else:
            normalized.pop("data", None)
            normalized.update(code=502, msg="接口响应格式异常", error="invalid_response")
            return normalized

    data = normalized.get("data")

    if path == "/firework/records" and isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                item.setdefault("receive", item.get("receiver", ""))
                item.setdefault("map_name", item.get("mapName", ""))
                item.setdefault("name", item.get("firework", ""))
    elif path == "/event/records" and isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("time") is None:
                item["time"] = 0
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
    elif path == "/fraud/detail" and isinstance(data, dict):
        if isinstance(data.get("records"), list):
            data["records"] = [_normalize_fraud_item(item) for item in data["records"] if isinstance(item, dict)]
        elif {"pid", "title", "content"} & set(data):
            normalized["data"] = _normalize_fraud_item(data)
    elif path == "/active/calendar" and isinstance(data, dict):
        data.setdefault("luck", data.get("lucky", []))
        weekly = data.get("weekly")
        if isinstance(weekly, dict):
            data.setdefault("team", list(weekly.get("conn") or []) + list(weekly.get("raid") or []))
    elif path in {"/news/records", "/news/announce", "/skill/rework"} and isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            item.setdefault("id", item.get("catid") or item.get("url") or "")
            desc = item.get("desc") if isinstance(item.get("desc"), dict) else {}
            if "time" not in item:
                item["time"] = (_timestamp(desc.get("inputtime")) or _timestamp(desc.get("asktime"))
                                or _timestamp(item.get("date")))
            elif isinstance(item.get("time"), str):
                item["time"] = _timestamp(item["time"])
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
        raw_time = item.get("lasttime") if item.get("legacyStatus") == 1 else item.get("shuttime")
        event_time = _timestamp(raw_time)
        if "time" not in item:
            item["time"] = event_time or sampled_at
            item["time_source"] = "upstream" if event_time else "observed"
