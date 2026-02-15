"""Background loop abstraction for ROT server.

Provides ``BackgroundLoop`` (a reusable async loop) and ``LoopManager``
(a registry that starts/stops all loops together).

Usage::

    mgr = LoopManager(stop_event)
    mgr.add("price_check", coro_fn=price_checker.check_pending_prices,
            interval_s=300, startup_delay_s=30)
    mgr.start_all()
    ...
    mgr.cancel_all()
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Awaitable, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

LoopFn = Callable[[], Awaitable[Any]]


class BackgroundLoop:
    """A single async background loop with startup delay and interruptible sleep."""

    def __init__(
        self,
        name: str,
        coro_fn: LoopFn,
        interval_s: int,
        stop_event: threading.Event,
        startup_delay_s: int = 0,
    ) -> None:
        self.name = name
        self.coro_fn = coro_fn
        self.interval_s = interval_s
        self.stop_event = stop_event
        self.startup_delay_s = startup_delay_s
        self._task: Optional[asyncio.Task] = None

    async def _run(self) -> None:
        log.info("%s loop starting (interval=%ds, delay=%ds)",
                 self.name, self.interval_s, self.startup_delay_s)

        # Startup delay (interruptible)
        for _ in range(self.startup_delay_s):
            if self.stop_event.is_set():
                return
            await asyncio.sleep(1)

        while not self.stop_event.is_set():
            try:
                await self.coro_fn()
            except Exception as e:
                log.error("%s loop error: %s", self.name, e, exc_info=True)

            # Interruptible sleep
            for _ in range(self.interval_s):
                if self.stop_event.is_set():
                    break
                await asyncio.sleep(1)

        log.info("%s loop stopped", self.name)

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run())
        return self._task

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()


class LoopManager:
    """Registry of background loops with collective start/stop."""

    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self._loops: Dict[str, BackgroundLoop] = {}

    def add(
        self,
        name: str,
        coro_fn: LoopFn,
        interval_s: int,
        startup_delay_s: int = 0,
    ) -> None:
        """Register a background loop."""
        self._loops[name] = BackgroundLoop(
            name=name,
            coro_fn=coro_fn,
            interval_s=interval_s,
            stop_event=self.stop_event,
            startup_delay_s=startup_delay_s,
        )

    def start_all(self) -> List[asyncio.Task]:
        """Start all registered loops. Returns list of tasks."""
        tasks = []
        for loop in self._loops.values():
            tasks.append(loop.start())
        log.info("LoopManager: started %d background loops", len(tasks))
        return tasks

    def cancel_all(self) -> None:
        """Cancel all running loops."""
        for loop in self._loops.values():
            loop.cancel()
        log.info("LoopManager: cancelled %d background loops", len(self._loops))

    @property
    def names(self) -> List[str]:
        return list(self._loops.keys())

    def __len__(self) -> int:
        return len(self._loops)
