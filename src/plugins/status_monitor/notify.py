from __future__ import annotations

from typing import Optional

import config as cfg
import httpx
from nonebot import logger

from src.infra.email_notify import send_email_async, send_email_via_163


async def get_NapCat_data() -> Optional[dict]:
    napcat_addr = getattr(cfg, "STATUS_MONITOR_NAPCAT_ADDR", "") or ""
    if not napcat_addr:
        raise RuntimeError("未配置 STATUS_MONITOR_NAPCAT_ADDR（示例：http://172.17.0.1:3001）")

    napcat_base_url = str(napcat_addr).strip().rstrip("/")

    napcat_status_url = f"{napcat_base_url}/get_status"
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            response = await client.get(napcat_status_url)
            if response.status_code != 200:
                logger.warning(
                    f"status_monitor NapCat status 返回错误: url={napcat_status_url}, status_code={response.status_code}"
                )
                return None
            return response.json()
    except Exception as exc:
        logger.warning(f"status_monitor NapCat status 请求失败: url={napcat_status_url}, exc={exc!r}")
        return None


__all__ = ["get_NapCat_data", "send_email_via_163", "send_email_async"]
