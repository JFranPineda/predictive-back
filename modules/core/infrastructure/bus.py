"""In-process event bus with an async escape hatch.

Handlers registered with `async_=True` are dispatched through Celery so a slow
listener never lengthens the request that fired the event.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

from modules.core.domain.events import DomainEvent

logger = logging.getLogger(__name__)

Handler = Callable[[DomainEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[Handler, bool]]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Handler, *, async_: bool = False) -> None:
        self._handlers[event_name].append((handler, async_))

    def publish(self, event: DomainEvent) -> None:
        for handler, async_ in self._handlers.get(event.name, []):
            if async_:
                from modules.core.infrastructure.tasks import dispatch_event

                dispatch_event.delay(event.name, _handler_path(handler), _serialize(event))
                continue
            try:
                handler(event)
            except Exception:  # a listener must never break the emitter
                logger.exception("handler %s failed on %s", _handler_path(handler), event.name)


def _handler_path(handler: Handler) -> str:
    return f"{handler.__module__}:{handler.__qualname__}"


def _serialize(event: DomainEvent) -> dict:
    from dataclasses import asdict

    return asdict(event)


bus = EventBus()
