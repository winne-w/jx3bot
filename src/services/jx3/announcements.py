from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def format_time(time_str: str) -> str:
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        month = dt.month
        day = dt.day
        hour = dt.hour
        minute = dt.minute

        if minute == 0:
            return f"{month}月{day}日 {hour}点"
        return f"{month}月{day}日 {hour}点{minute}分"
    except Exception:
        return time_str


def parse_updates(data: Any, keyword: str) -> list[dict[str, str]]:
    try:
        if isinstance(data, str):
            data = json.loads(data)
        elif not isinstance(data, dict):
            return []

        if data.get("code") != 200:
            return []

        items = data.get("data", [])
        filtered_items = [item for item in items if keyword in item.get("title", "")]
        if not filtered_items:
            return []

        for item in filtered_items:
            item["datetime"] = datetime.strptime(item["time"], "%Y-%m-%d %H:%M:%S")

        filtered_items.sort(key=lambda x: x["datetime"], reverse=True)
        latest_time = filtered_items[0]["datetime"]

        latest_items = [
            {"id": item["id"], "url": item["url"], "title": item["title"], "time": item["time"]}
            for item in filtered_items
            if item["datetime"] == latest_time
        ]
        return latest_items
    except Exception:
        return []


def parse_updateshuodong(data: Any, keyword: str) -> list[dict[str, str]]:
    try:
        if isinstance(data, str):
            data = json.loads(data)
        elif not isinstance(data, dict):
            return []

        if data.get("code") != 200:
            return []

        items = data.get("data", [])
        filtered_items = [item for item in items if keyword in item.get("title", "")]
        if not filtered_items:
            return []

        try:
            if "id" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["id"]), reverse=True)
            elif "token" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["token"]), reverse=True)
        except Exception:
            pass

        unique_titles: set[str] = set()
        latest_items: list[dict[str, Any]] = []

        for item in filtered_items:
            title = item.get("title", "")
            if title not in unique_titles:
                unique_titles.add(title)
                latest_items.append(item)
            if len(latest_items) >= 3:
                break

        result_items: list[dict[str, str]] = []
        for item in latest_items:
            result_items.append(
                {
                    "id": str(item.get("id", item.get("token", ""))),
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "time": item.get("date", ""),
                }
            )

        return result_items
    except Exception:
        return []


def parse_updatesnew(data: Any, keyword: str) -> list[dict[str, str]]:
    try:
        if isinstance(data, str):
            data = json.loads(data)
        elif not isinstance(data, dict):
            return []

        if data.get("code") != 200:
            return []

        items = data.get("data", [])
        filtered_items = [item for item in items if keyword in item.get("title", "")]
        if not filtered_items:
            return []

        try:
            if "id" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["id"]), reverse=True)
            elif "token" in filtered_items[0]:
                filtered_items.sort(key=lambda x: int(x["token"]), reverse=True)
        except Exception:
            pass

        latest_id = (
            filtered_items[0].get("id") if "id" in filtered_items[0] else filtered_items[0].get("token")
        )

        if "id" in filtered_items[0]:
            latest_items = [item for item in filtered_items if item["id"] == latest_id]
        else:
            latest_items = [item for item in filtered_items if item["token"] == latest_id]

        if not latest_items:
            latest_items = [filtered_items[0]]

        result_items: list[dict[str, str]] = []
        for item in latest_items:
            result_items.append(
                {
                    "id": str(item.get("id", item.get("token", ""))),
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "time": item.get("date", ""),
                }
            )

        return result_items
    except Exception:
        return []

