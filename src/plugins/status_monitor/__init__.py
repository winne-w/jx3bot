from nonebot import get_driver
from nonebot.plugin import require

require("nonebot_plugin_apscheduler")

from . import commands as _commands  # noqa: F401
from . import jobs as _jobs  # noqa: F401

driver = get_driver()


@driver.on_startup
async def init() -> None:
    _jobs.log_startup()


@driver.on_bot_connect
async def _on_bot_connect(bot) -> None:
    _jobs.set_bot_initialized(True)
