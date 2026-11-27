from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

import config as cfg
from src.utils.tuilan_auth_alert import register_alert_handlers

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    logger = logging.getLogger(__name__)

_PLACEHOLDER_MAIL_MARKERS = ("用于qq掉线提醒",)


def resolve_smtp_password() -> str:
    raw_password = str(getattr(cfg, "STATUS_MONITOR_SMTP_PASSWORD", "") or "").strip()
    if raw_password:
        return raw_password
    legacy_mail = str(getattr(cfg, "mail", "") or "").strip()
    if legacy_mail and not any(marker in legacy_mail for marker in _PLACEHOLDER_MAIL_MARKERS):
        return legacy_mail
    return ""


def _resolve_smtp_port() -> int:
    raw_port = getattr(cfg, "STATUS_MONITOR_SMTP_PORT", 465)
    try:
        port = int(str(raw_port).strip())
        return port if port > 0 else 465
    except (TypeError, ValueError):
        return 465


def send_email_via_163(content: str, subject: Optional[str] = None) -> bool:
    smtp_username = str(getattr(cfg, "STATUS_MONITOR_SMTP_USERNAME", "") or "").strip()
    smtp_password = resolve_smtp_password()
    email_from = str(getattr(cfg, "STATUS_MONITOR_EMAIL_FROM", "") or "").strip() or smtp_username
    email_to = getattr(cfg, "STATUS_MONITOR_EMAIL_TO", "")
    raw_subject = subject if subject is not None else getattr(cfg, "STATUS_MONITOR_EMAIL_SUBJECT", "")
    email_subject = str(raw_subject or "").strip() or "服务器状态提醒"
    smtp_server = str(getattr(cfg, "STATUS_MONITOR_SMTP_SERVER", "smtp.163.com") or "smtp.163.com").strip()
    port = _resolve_smtp_port()

    if not smtp_username or not smtp_password or not email_from or not email_to:
        logger.warning("status_monitor 邮件配置不完整，跳过发送")
        return False

    msg = EmailMessage()
    msg["Subject"] = email_subject
    msg["From"] = email_from
    if isinstance(email_to, (list, tuple, set)):
        msg["To"] = ",".join(str(addr).strip() for addr in email_to if str(addr).strip())
    else:
        msg["To"] = str(email_to).strip()
    if not msg["To"]:
        logger.warning("status_monitor 收件人邮箱为空，跳过发送")
        return False
    msg.set_content(content)

    try:
        with smtplib.SMTP_SSL(smtp_server, port, timeout=15) as server:
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            logger.info("status_monitor 邮件发送成功")
            return True
    except Exception as exc:
        logger.warning(f"status_monitor 发送邮件失败: {exc}")
        return False


async def send_email_async(content: str, subject: Optional[str] = None) -> bool:
    return await asyncio.to_thread(send_email_via_163, content, subject)


register_alert_handlers(sync_email_sender=send_email_via_163)
