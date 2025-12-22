from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BaizhanCachePaths:
    image_path: str
    data_path: str


def baizhan_cache_paths(image_dir: str = "data/baizhan_images") -> BaizhanCachePaths:
    os.makedirs(image_dir, exist_ok=True)
    return BaizhanCachePaths(
        image_path=os.path.join(image_dir, "baizhan_latest.png"),
        data_path=os.path.join(image_dir, "baizhan_data.json"),
    )


def load_cached_baizhan_image_bytes(paths: BaizhanCachePaths, *, now_ts: int) -> bytes | None:
    if not (os.path.exists(paths.data_path) and os.path.exists(paths.image_path)):
        return None

    try:
        with open(paths.data_path, "r", encoding="utf-8") as f:
            local_data = json.load(f)
        end_timestamp = int(local_data.get("end_timestamp", 0) or 0)
        if end_timestamp <= now_ts:
            return None
        with open(paths.image_path, "rb") as img_file:
            return img_file.read()
    except Exception:
        return None


def save_baizhan_cache(paths: BaizhanCachePaths, *, result: dict[str, Any], image_bytes: bytes) -> None:
    with open(paths.data_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "start_timestamp": result.get("start_timestamp"),
                "end_timestamp": result.get("end_timestamp"),
                "result": result,
            },
            f,
            ensure_ascii=False,
        )
    with open(paths.image_path, "wb") as f:
        f.write(image_bytes)


def parse_baizhan_data(json_data: str | dict[str, Any]) -> dict[str, Any]:
    """
    解析百战异闻录数据，提取渲染所需字段。
    """
    if isinstance(json_data, str):
        data = json.loads(json_data)
    elif isinstance(json_data, dict):
        data = json_data
    else:
        raise TypeError("输入必须是JSON字符串或字典")

    start_timestamp = data["data"]["start"]
    end_timestamp = data["data"]["end"]
    start_date = datetime.fromtimestamp(start_timestamp).strftime("%m/%d")
    end_date = datetime.fromtimestamp(end_timestamp).strftime("%m/%d")

    all_items: list[dict[str, Any]] = []
    for item in data["data"]["data"]:
        item_result: dict[str, Any] = {
            "level": item["level"],
            "name": item["name"],
            "skill": item["skill"],
            "list_result": False,
            "list_items": {},
        }

        if "data" in item and "list" in item["data"]:
            item_list = item["data"]["list"]
            if item_list and len(item_list) > 0:
                item_result["list_result"] = True
                if len(item_list) > 0:
                    item_result["list_items"]["list_0"] = item_list[0]
                if len(item_list) > 1:
                    item_result["list_items"]["list_1"] = item_list[1]

        if "data" in item and "desc" in item["data"]:
            item_result["desc"] = item["data"]["desc"]

        all_items.append(item_result)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "total_items": len(all_items),
        "items": all_items,
    }

