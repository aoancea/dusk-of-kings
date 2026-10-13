"""Tiny publish/subscribe event bus used to decouple game systems."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Handler = Callable[..., Any]


class EventBus:
    """Synchronous event dispatcher: ``bus.on('enemy_killed', fn)`` / ``bus.emit('enemy_killed', enemy=e)``."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, name: str, handler: Handler) -> None:
        if handler not in self._handlers[name]:
            self._handlers[name].append(handler)

    def off(self, name: str, handler: Handler) -> None:
        if handler in self._handlers[name]:
            self._handlers[name].remove(handler)

    def emit(self, event: str, /, **kwargs: Any) -> None:
        for handler in list(self._handlers.get(event, ())):
            handler(**kwargs)

    def clear(self) -> None:
        self._handlers.clear()


events = EventBus()
