import asyncio
import logging
import socket
import time
from typing import List

import config as cfg
from src.services.jx3.singletons import jjc_match_data_sync_service

logger = logging.getLogger(__name__)

_TASKS: List[asyncio.Task] = []
_DISPATCHER_TASKS: List[asyncio.Task] = []

_RESTART_BACKOFF_INITIAL = 1.0
_RESTART_BACKOFF_MAX = 60.0
_HEALTHY_RESET_SECONDS = 60.0
_AUTO_PAUSED_SLEEP_SECONDS = 10.0


def _build_worker_id(index: int) -> str:
    host = socket.gethostname()
    return f"bot:{host}:{index}"


async def _run_worker(worker_id: str) -> None:
    delay = _RESTART_BACKOFF_INITIAL
    while True:
        started = time.monotonic()
        try:
            summary = await jjc_match_data_sync_service.run_worker(
                mode="full",
                worker_id=worker_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if time.monotonic() - started >= _HEALTHY_RESET_SECONDS:
                delay = _RESTART_BACKOFF_INITIAL
            logger.exception(
                f"Bot-managed JJC sync worker exited with error, restarting in {delay}s: worker_id={worker_id}"
            )
            await asyncio.sleep(delay)
            delay = min(_RESTART_BACKOFF_MAX, delay * 2)
            continue

        if time.monotonic() - started >= _HEALTHY_RESET_SECONDS:
            delay = _RESTART_BACKOFF_INITIAL

        if isinstance(summary, dict) and summary.get("stopped_reason") == "auto_paused":
            await asyncio.sleep(_AUTO_PAUSED_SLEEP_SECONDS)
            continue

        if isinstance(summary, dict) and summary.get("error"):
            logger.warning(
                "Bot-managed JJC sync worker returned error summary, restarting in "
                f"{delay}s: worker_id={worker_id} message={summary.get('message')}"
            )
            await asyncio.sleep(delay)
            delay = min(_RESTART_BACKOFF_MAX, delay * 2)
            continue

        await asyncio.sleep(_RESTART_BACKOFF_INITIAL)


async def _run_dispatcher() -> None:
    delay = _RESTART_BACKOFF_INITIAL
    while True:
        started = time.monotonic()
        try:
            summary = await jjc_match_data_sync_service.run_dispatcher()
        except asyncio.CancelledError:
            raise
        except Exception:
            if time.monotonic() - started >= _HEALTHY_RESET_SECONDS:
                delay = _RESTART_BACKOFF_INITIAL
            logger.exception(
                f"Bot-managed JJC sync dispatcher exited with error, restarting in {delay}s"
            )
            await asyncio.sleep(delay)
            delay = min(_RESTART_BACKOFF_MAX, delay * 2)
            continue

        if time.monotonic() - started >= _HEALTHY_RESET_SECONDS:
            delay = _RESTART_BACKOFF_INITIAL

        if isinstance(summary, dict) and summary.get("stopped_reason") == "auto_paused":
            await asyncio.sleep(_AUTO_PAUSED_SLEEP_SECONDS)
            continue

        if isinstance(summary, dict) and summary.get("error"):
            logger.warning(
                "Bot-managed JJC sync dispatcher returned error summary, restarting in "
                f"{delay}s: message={summary.get('message')}"
            )
            await asyncio.sleep(delay)
            delay = min(_RESTART_BACKOFF_MAX, delay * 2)
            continue

        await asyncio.sleep(_RESTART_BACKOFF_INITIAL)


async def start_jjc_sync_workers() -> None:
    global _TASKS

    active_tasks = [task for task in _TASKS if not task.done()]
    if active_tasks:
        _TASKS = active_tasks
        logger.warning(f"Bot-managed JJC sync workers already running: count={len(_TASKS)}")
        return

    try:
        worker_count = int(getattr(cfg, "JJC_SYNC_WORKER_COUNT", 0))
    except (TypeError, ValueError):
        logger.error("Invalid JJC_SYNC_WORKER_COUNT, skip bot-managed workers")
        _TASKS = []
        return

    if worker_count < 0:
        logger.error(f"Invalid JJC_SYNC_WORKER_COUNT={worker_count}, skip bot-managed workers")
        _TASKS = []
        return

    if worker_count == 0:
        _TASKS = []
        logger.info("Bot-managed JJC sync workers disabled")
        return

    _TASKS = [
        asyncio.create_task(_run_worker(_build_worker_id(index)))
        for index in range(worker_count)
    ]
    logger.info(f"Started bot-managed JJC sync workers: count={worker_count}")


async def start_jjc_sync_dispatcher() -> None:
    global _DISPATCHER_TASKS

    active_tasks = [task for task in _DISPATCHER_TASKS if not task.done()]
    if active_tasks:
        _DISPATCHER_TASKS = active_tasks
        logger.warning("Bot-managed JJC sync dispatcher already running")
        return

    enabled = int(getattr(cfg, "JJC_SYNC_DISPATCHER_ENABLED", 1))
    if enabled <= 0:
        _DISPATCHER_TASKS = []
        logger.info("Bot-managed JJC sync dispatcher disabled")
        return

    _DISPATCHER_TASKS = [asyncio.create_task(_run_dispatcher())]
    logger.info("Started bot-managed JJC sync dispatcher")


async def stop_jjc_sync_workers() -> None:
    global _TASKS

    tasks = [task for task in _TASKS if not task.done()]
    _TASKS = []
    if not tasks:
        return

    for task in tasks:
        task.cancel()

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.warning(f"Failed to stop bot-managed JJC sync workers: error={exc}")
        return

    for result in results:
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            logger.warning(f"Bot-managed JJC sync worker stopped with error: error={result}")


async def stop_jjc_sync_dispatcher() -> None:
    global _DISPATCHER_TASKS

    tasks = [task for task in _DISPATCHER_TASKS if not task.done()]
    _DISPATCHER_TASKS = []
    if not tasks:
        return

    for task in tasks:
        task.cancel()

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        logger.warning(f"Failed to stop bot-managed JJC sync dispatcher: error={exc}")
        return

    for result in results:
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            logger.warning(f"Bot-managed JJC sync dispatcher stopped with error: error={result}")
