from __future__ import annotations

import smtplib

import config as cfg
import httpx
from email.message import EmailMessage


async def get_NapCat_data() -> dict | None:
    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get("http://192.168.100.1:3000/get_status")
            if response.status_code != 200:
                print(f"技改API返回错误: {response.status_code}")
                return None
            return response.json()
    except Exception as exc:
        print(f"请求技改API出错: {exc}")
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
        print("邮件配置不完整，跳过发送（需要配置 STATUS_MONITOR_SMTP_USERNAME/SMTP_PASSWORD/EMAIL_FROM/EMAIL_TO）")
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
            print("邮件发送成功！")
            return True
    except Exception as exc:
        print(f"发送邮件时出错: {exc}")
        return False
