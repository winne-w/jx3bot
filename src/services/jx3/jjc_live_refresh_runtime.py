import asyncio
from typing import Optional

import config
from nonebot import logger

from src.infra.managed_task import LoopLocal

_task: Optional[asyncio.Task] = None
_lifecycle_lock_local: LoopLocal[asyncio.Lock] = LoopLocal(asyncio.Lock)


def _lifecycle_lock() -> asyncio.Lock:
    return _lifecycle_lock_local.get()


async def start_live_refresh() -> None:
    global _task
    async with _lifecycle_lock():
        if _task and not _task.done():
            return
        from src.services.jx3.singletons import jjc_live_refresh_service as service
        if not service.enabled():
            return
        if not getattr(config, "JJC_LIVE_SOURCE_SECRET", ""):
            logger.error("JJC latest refresh requires JJC_LIVE_SOURCE_SECRET")
            return
        try:
            state = await service.readiness()
            if state.get("state") != "ready":
                logger.warning("JJC latest refresh worker not started: state={}", state.get("state"))
                return
            await service.repo.initialize()
        except Exception as exc:
            # This optional worker must not prevent the bot and local APIs from starting.
            logger.error("JJC latest refresh worker initialization failed: exception_type={}", type(exc).__name__)
            return
        _task = asyncio.create_task(service.run_worker())
        _task.add_done_callback(_report_exit)


def _report_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.error("JJC latest refresh worker stopped: exception_type={}", type(task.exception()).__name__)


async def stop_live_refresh() -> None:
    global _task
    async with _lifecycle_lock():
        task, _task = _task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
