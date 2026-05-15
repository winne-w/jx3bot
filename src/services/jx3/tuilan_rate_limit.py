from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable

from nonebot import logger


async def random_sleep(
    min_seconds: float = 1.0,
    max_seconds: float = 3.0,
    sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    delay = random.uniform(min_seconds, max_seconds)
    logger.info(f"等待 {delay:.2f} 秒后发起请求")
    await sleep_func(delay)


async def fixed_sleep(
    seconds: float = 5.45,
    sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    logger.info(f"等待 {seconds:.2f} 秒后发起请求")
    await sleep_func(seconds)
