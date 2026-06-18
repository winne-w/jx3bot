#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import nonebot
from nonebot.adapters.onebot.v11 import Adapter

from src.api import register_api

# You can pass some keyword args config to init function
nonebot.init()
app = nonebot.get_asgi()
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

register_api(app)


@driver.on_startup
async def _startup_mongo():
    from config import MONGO_URI
    from src.infra.mongo import init_mongo
    from src.services.jx3.jjc_sync_worker_runtime import start_jjc_sync_dispatcher, start_jjc_sync_workers

    await init_mongo(MONGO_URI)
    await start_jjc_sync_workers()
    await start_jjc_sync_dispatcher()


@driver.on_shutdown
async def _shutdown_jjc_sync_workers():
    from src.services.jx3.jjc_sync_worker_runtime import stop_jjc_sync_dispatcher, stop_jjc_sync_workers

    await stop_jjc_sync_dispatcher()
    await stop_jjc_sync_workers()


# Please DO NOT modify this file unless you know what you are doing!
# As an alternative, you should use command `nb` or modify `pyproject.toml` to load plugins
nonebot.load_from_toml("pyproject.toml")

# Modify some config / config depends on loaded configs
#
# config = driver.config
# do something...


if __name__ == "__main__":
    nonebot.logger.warning("Always use `nb run` to start the bot instead of manually running!")
    nonebot.run(app="__mp_main__:app")
