import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Generic, Optional, TypeVar
from weakref import WeakKeyDictionary

T = TypeVar("T")


class LoopLocal(Generic[T]):
    """Lazily create and cache one instance per running asyncio event loop."""

    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._instances: "WeakKeyDictionary[asyncio.AbstractEventLoop, T]" = WeakKeyDictionary()

    def get(self, *, on_loop_change: Optional[Callable[[], None]] = None) -> T:
        loop = asyncio.get_running_loop()
        instance = self._instances.get(loop)
        if instance is None:
            if on_loop_change is not None:
                on_loop_change()
            instance = self._factory()
            self._instances[loop] = instance
        return instance

    def clear(self) -> None:
        self._instances.clear()


async def supervise_forever(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    name: str,
    logger_obj: Any,
    initial_backoff: float = 1.0,
    max_backoff: float = 60.0,
    healthy_reset_seconds: float = 60.0,
    auto_paused_sleep: float = 10.0,
) -> None:
    """Run ``coro_factory`` in a supervised loop with bounded exponential backoff.

    - ``asyncio.CancelledError`` is always propagated immediately.
    - Non-cancel exceptions or dict summaries with truthy ``error`` trigger
      exponential backoff restarts (resetting to ``initial_backoff`` once a
      run stays healthy for ``healthy_reset_seconds``).
    - Dict summaries with ``stopped_reason == "auto_paused"`` sleep for
      ``auto_paused_sleep`` seconds before restarting.
    """
    delay = initial_backoff
    while True:
        started = time.monotonic()
        try:
            summary = await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception:
            if time.monotonic() - started >= healthy_reset_seconds:
                delay = initial_backoff
            logger_obj.exception(
                f"{name} exited with error, restarting in {delay}s"
            )
            await asyncio.sleep(delay)
            delay = min(max_backoff, delay * 2)
            continue

        if time.monotonic() - started >= healthy_reset_seconds:
            delay = initial_backoff

        if isinstance(summary, dict) and summary.get("stopped_reason") == "auto_paused":
            await asyncio.sleep(auto_paused_sleep)
            continue

        if isinstance(summary, dict) and summary.get("error"):
            logger_obj.warning(
                f"{name} returned error summary, restarting in {delay}s: "
                f"message={summary.get('message')}"
            )
            await asyncio.sleep(delay)
            delay = min(max_backoff, delay * 2)
            continue

        await asyncio.sleep(initial_backoff)


class ManagedBackgroundTask:
    """Lifecycle manager for a single supervised background asyncio task."""

    def __init__(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        name: str,
        logger_obj: Any,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        healthy_reset_seconds: float = 60.0,
        auto_paused_sleep: float = 10.0,
    ) -> None:
        self._coro_factory = coro_factory
        self._name = name
        self._logger = logger_obj
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._healthy_reset_seconds = healthy_reset_seconds
        self._auto_paused_sleep = auto_paused_sleep
        self._lock_local: LoopLocal[asyncio.Lock] = LoopLocal(asyncio.Lock)
        self._task: Optional[asyncio.Task] = None
        self._started_count = 0

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "name": self._name,
            "running": self.is_running(),
            "started_count": self._started_count,
        }

    async def start(self) -> bool:
        async with self._lock_local.get():
            if self.is_running():
                return False
            self._started_count += 1
            self._task = asyncio.create_task(
                supervise_forever(
                    self._coro_factory,
                    name=self._name,
                    logger_obj=self._logger,
                    initial_backoff=self._initial_backoff,
                    max_backoff=self._max_backoff,
                    healthy_reset_seconds=self._healthy_reset_seconds,
                    auto_paused_sleep=self._auto_paused_sleep,
                )
            )
            return True

    async def stop(self) -> None:
        async with self._lock_local.get():
            task, self._task = self._task, None
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
