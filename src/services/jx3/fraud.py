from __future__ import annotations

import time
from typing import Any


def format_scammer_reply(data: dict[str, Any]) -> str:
    if (
        data.get("code") != 200
        or "data" not in data
        or "records" not in data["data"]
        or not data["data"]["records"]
    ):
        return "未查询到相关骗子信息，该接口只能查剑网三相关的，别的不如百度请慎用！"

    records = data["data"]["records"]

    reply = "⚠️ 查询到骗子记录 ⚠️\n"
    reply += "------------------------\n"

    for i, record in enumerate(records, 1):
        server = record.get("server", "")
        tieba = record.get("tieba", "")

        reply += f"来源{i}: {tieba} ({server})\n"

        for j, item in enumerate(record.get("data", []), 1):
            title = item.get("title", "")
            url = item.get("url", "")
            text = str(item.get("text", "")).replace("\n", " ")
            time_str = time.strftime("%Y-%m-%d", time.localtime(item.get("time", 0)))

            reply += f"• 标题: {title}\n"
            reply += f"• 内容: {text}\n"
            reply += f"• 时间: {time_str}\n"
            reply += f"• 链接: {url}\n"

            if j < len(record.get("data", [])):
                reply += "--------------------\n"

        if i < len(records):
            reply += "========================\n"

    reply += "\n⚠️ 请注意防范诈骗，谨慎交易 ⚠️"
    return reply

