"""Task scheduler: keep UI non-blocking (PRD §3.3: >16ms goes to workers)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class TaskHandle:
    name: str
    task: asyncio.Task[Any]


class TaskScheduler:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskHandle] = {}

    def spawn(self, name: str, coro: Awaitable[Any]) -> TaskHandle:
        self.cancel(name)
        task = asyncio.ensure_future(coro)
        handle = TaskHandle(name=name, task=task)
        self._tasks[name] = handle
        task.add_done_callback(lambda _t: self._tasks.pop(name, None))
        return handle

    def run_in_thread(
        self, name: str, fn: Callable[..., Any], *args: Any
    ) -> TaskHandle:
        async def _wrap() -> Any:
            return await asyncio.to_thread(fn, *args)

        return self.spawn(name, _wrap())

    def cancel(self, name: str) -> bool:
        handle = self._tasks.get(name)
        if handle is None:
            return False
        handle.task.cancel()
        return True

    async def shutdown(self) -> None:
        for name in list(self._tasks):
            self.cancel(name)
        if self._tasks:
            await asyncio.gather(
                *(h.task for h in self._tasks.values()), return_exceptions=True
            )

    def running(self) -> list[str]:
        return sorted(self._tasks.keys())
