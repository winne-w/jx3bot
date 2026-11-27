from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple


DEFAULT_SEASONS_CACHE_TTL_SECONDS = 30.0
DEFAULT_MAX_CACHE_KEYS = 16


class JjcSeasonsCacheService:
    """Short-TTL memory cache with epoch-fenced singleflight for JJC seasons metadata."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_SEASONS_CACHE_TTL_SECONDS,
        max_keys: int = DEFAULT_MAX_CACHE_KEYS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self.max_keys = max(1, int(max_keys))
        self._monotonic = monotonic
        self._cache: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()
        self._inflight: Dict[str, Tuple[asyncio.Task, int]] = {}
        self._epochs: Dict[str, int] = {}
        self._global_epoch: int = 0

    def _current_epoch(self, cache_key: str) -> Tuple[int, int]:
        return (self._global_epoch, self._epochs.get(cache_key, 0))

    def invalidate(self, cache_key: Optional[str] = None) -> None:
        if cache_key is None:
            self._global_epoch += 1
            self._cache.clear()
            self._inflight.clear()
            return
        self._epochs[cache_key] = self._epochs.get(cache_key, 0) + 1
        self._cache.pop(cache_key, None)
        self._inflight.pop(cache_key, None)

    def _store_if_fresh(
        self,
        cache_key: str,
        started_epoch: Tuple[int, int],
        result: Dict[str, Any],
    ) -> None:
        if self.ttl_seconds <= 0:
            return
        if not isinstance(result, dict) or not result.get("seasons"):
            return
        if self._current_epoch(cache_key) != started_epoch:
            return
        self._cache[cache_key] = (
            self._monotonic() + self.ttl_seconds,
            deepcopy(result),
        )
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self.max_keys:
            self._cache.popitem(last=False)

    async def get_seasons(
        self,
        fetcher: Callable[[], Awaitable[Dict[str, Any]]],
        *,
        cache_key: str = "default",
    ) -> Dict[str, Any]:
        if self.ttl_seconds > 0:
            cached = self._cache.get(cache_key)
            if cached is not None:
                expires_at, payload = cached
                if self._monotonic() < expires_at:
                    self._cache.move_to_end(cache_key)
                    return deepcopy(payload)
                self._cache.pop(cache_key, None)

        entry = self._inflight.get(cache_key)
        if entry is None or entry[0].done():
            started_epoch = self._current_epoch(cache_key)

            async def _run() -> Dict[str, Any]:
                result = await fetcher()
                self._store_if_fresh(cache_key, started_epoch, result)
                return result

            task = asyncio.create_task(_run())

            def _on_done(done_task: asyncio.Task) -> None:
                current = self._inflight.get(cache_key)
                if current is not None and current[0] is done_task:
                    self._inflight.pop(cache_key, None)
                if not done_task.cancelled():
                    # Consume any exception so asyncio never logs
                    # "Task exception was never retrieved" if all waiters cancelled.
                    done_task.exception()

            task.add_done_callback(_on_done)
            self._inflight[cache_key] = (task, 1)
        else:
            task, waiters = entry
            self._inflight[cache_key] = (task, waiters + 1)

        cancelled = False
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            current = self._inflight.get(cache_key)
            if current is not None and current[0] is task:
                remaining = current[1] - 1
                if remaining <= 0:
                    self._inflight.pop(cache_key, None)
                    if cancelled and not task.done():
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                else:
                    self._inflight[cache_key] = (task, remaining)

        return deepcopy(result)


jjc_seasons_cache_service = JjcSeasonsCacheService()
