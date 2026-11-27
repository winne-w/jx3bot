import asyncio
import config as cfg
from nonebot import get_driver, logger
from nonebot.plugin import require

require("nonebot_plugin_apscheduler")

from src.infra.email_notify import send_email_via_163
from src.utils.tuilan_auth_alert import clear_runtime_handlers, register_alert_handlers
from . import commands as _commands  # noqa: F401
from . import jobs as _jobs  # noqa: F401

driver = get_driver()

log_startup = _jobs.log_startup
set_bot_initialized = _jobs.set_bot_initialized

__all__ = ["driver", "init", "log_startup", "set_bot_initialized"]


async def _send_admin_qq_alert(message: str) -> bool:
    bots = getattr(get_driver(), "bots", None) or {}
    bot = next(iter(bots.values()), None)
    admin_qqs = list(getattr(cfg, "ADMIN_QQ", []) or [])
    if bot is None or not admin_qqs:
        return False
    sent_any = False
    for admin_qq in admin_qqs:
        try:
            await bot.send_private_msg(user_id=int(admin_qq), message=message)
            sent_any = True
        except Exception as exc:
            logger.warning(f"status_monitor 私聊管理员 {admin_qq} 失败: {exc}")
    return sent_any


@driver.on_startup
async def init() -> None:
    _jobs.reset_napcat_monitor_start()
    register_alert_handlers(
        async_qq_sender=_send_admin_qq_alert,
        sync_email_sender=send_email_via_163,
        loop=asyncio.get_running_loop(),
    )
    _jobs.log_startup()


@driver.on_shutdown
async def shutdown() -> None:
    clear_runtime_handlers()


@driver.on_bot_connect
async def _on_bot_connect(bot) -> None:
    _jobs.set_bot_initialized(True)
