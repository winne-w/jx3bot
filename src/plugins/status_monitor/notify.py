from __future__ import annotations

import smtplib

import config as cfg
import httpx
from email.message import EmailMessage
from nonebot import logger


async def get_NapCat_data() -> dict | None:
    napcat_addr = getattr(cfg, "STATUS_MONITOR_NAPCAT_ADDR", "") or ""
    if not napcat_addr:
        raise RuntimeError("未配置 STATUS_MONITOR_NAPCAT_ADDR（示例：http://172.17.0.1:3001）")

    napcat_base_url = str(napcat_addr).strip().rstrip("/")

    napcat_status_url = f"{napcat_base_url}/get_status"
    try:
        async with httpx.AsyncClient(verify=False) as client:
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


def send_email_via_163(content: str) -> bool:
    smtp_username = getattr(cfg, "STATUS_MONITOR_SMTP_USERNAME", "") or ""
    smtp_password = getattr(cfg, "STATUS_MONITOR_SMTP_PASSWORD", "") or getattr(cfg, "mail", "") or ""
    email_from = getattr(cfg, "STATUS_MONITOR_EMAIL_FROM", "") or smtp_username
    email_to = getattr(cfg, "STATUS_MONITOR_EMAIL_TO", "")
    email_subject = getattr(cfg, "STATUS_MONITOR_EMAIL_SUBJECT", "服务器状态提醒")
    smtp_server = getattr(cfg, "STATUS_MONITOR_SMTP_SERVER", "smtp.163.com")
    port = int(getattr(cfg, "STATUS_MONITOR_SMTP_PORT", 465))

    if not smtp_username or not smtp_password or not email_from or not email_to:
        logger.warning("status_monitor 邮件配置不完整，跳过发送")
        return False

    msg = EmailMessage()
    msg["Subject"] = email_subject
    msg["From"] = email_from
    if isinstance(email_to, (list, tuple, set)):
        msg["To"] = ",".join(map(str, email_to))
    else:
        msg["To"] = str(email_to)
    msg.set_content(content)

    try:
        with smtplib.SMTP_SSL(smtp_server, port) as server:
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            logger.info("status_monitor 邮件发送成功")
            return True
    except Exception as exc:
        logger.warning("status_monitor 发送邮件失败: {}", exc)
        return False
