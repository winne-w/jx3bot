"""A single optional local consumer, independent of the QQ connection."""
import asyncio
from typing import Any, Optional

import config as cfg
from nonebot import logger

from src.storage.mongo_repos.jjc_kungfu_refresh_repo import QueueIntegrityError

_task: Optional[asyncio.Task] = None
_start_lock: Optional[asyncio.Lock] = None
_lock_loop: Optional[asyncio.AbstractEventLoop] = None


def _lifecycle_lock() -> asyncio.Lock:
    # Python 3.9 locks bind to the loop at construction, so do not create one
    # during module import. Reinitializing after a stopped loop also aids tests.
    global _start_lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _start_lock is None or _lock_loop is not loop:
        if _task is not None and not _task.done():
            raise RuntimeError("kungfu consumer belongs to another event loop")
        _start_lock, _lock_loop = asyncio.Lock(), loop
    return _start_lock


async def _run(service: Any) -> None:
    while True:
        try:
            worked = await service.run_once()
        except asyncio.CancelledError:
            raise
        except QueueIntegrityError:
            # Do not advance regressed counters through the normal retry loop.
            # The task exit callback reports the fatal type for maintenance.
            raise
        except Exception as exc:
            logger.error("JJC kungfu refresh attempt failed: exception_type={}", type(exc).__name__)
            worked = False
        if not worked:
            await asyncio.sleep(2)


def _report_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("JJC kungfu refresh consumer exited: exception_type={}",
                     type(task.exception()).__name__)


async def start_kungfu_refresh(service: Any = None) -> None:
    global _task
    async with _lifecycle_lock():
        if _task is not None and not _task.done():
            return
        if not getattr(cfg, "JJC_KUNGFU_REFRESH_ENABLED", 0):
            return
        try:
            if service is None:
                from src.services.jx3.singletons import jjc_kungfu_refresh_service
                service = jjc_kungfu_refresh_service
            await service.initialize()
        except Exception as exc:
            logger.error("JJC kungfu refresh not started: exception_type={}", type(exc).__name__)
            return
        _task = asyncio.create_task(_run(service))
        _task.add_done_callback(_report_exit)


async def stop_kungfu_refresh() -> None:
    global _task
    async with _lifecycle_lock():
        task, _task = _task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
