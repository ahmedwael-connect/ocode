"""Decoupled async event bus (PRD §3.3: engines talk via bus only)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

Handler = Callable[..., Awaitable[None] | None]


@dataclass
class Subscription:
    topic: str
    handler: Handler


class EventBus:
    """Minimal typed pub/sub bus. Sync handlers run inline; async ones awaited."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> Subscription:
        self._subs[topic].append(handler)
        return Subscription(topic, handler)

    def unsubscribe(self, sub: Subscription) -> None:
        handlers = self._subs.get(sub.topic, [])
        if sub.handler in handlers:
            handlers.remove(sub.handler)

    def topics(self) -> list[str]:
        return sorted(self._subs.keys())

    async def emit(self, topic: str, *args: Any, **kwargs: Any) -> int:
        """Emit to all subscribers. Returns number of handlers called."""
        count = 0
        for handler in list(self._subs.get(topic, ())):
            result = handler(*args, **kwargs)
            if asyncio.iscoroutine(result):
                await result
            count += 1
        return count

    def emit_nowait(self, topic: str, *args: Any, **kwargs: Any) -> asyncio.Task[int]:
        return asyncio.ensure_future(self.emit(topic, *args, **kwargs))
