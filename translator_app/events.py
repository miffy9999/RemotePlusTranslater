from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    """Thread-safe fan-out with bounded clients and replayable recent history."""

    def __init__(self, history_size: int = 100, subscriber_size: int = 100):
        self._history: deque[Event] = deque(maxlen=history_size)
        self._subscribers: set[queue.Queue[Event]] = set()
        self._subscriber_size = subscriber_size
        self._lock = threading.Lock()

    def publish(self, event_type: str, **data: Any) -> Event:
        event = Event(event_type, data)
        with self._lock:
            if event_type in {"translation", "error", "warning"}:
                self._history.append(event)
            self._fan_out_locked(event)
        return event

    def _fan_out_locked(self, event: Event) -> None:
        for target in tuple(self._subscribers):
            try:
                target.put_nowait(event)
            except queue.Full:
                try:
                    target.get_nowait()
                    target.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass

    def subscribe(self) -> queue.Queue[Event]:
        target: queue.Queue[Event] = queue.Queue(maxsize=self._subscriber_size)
        with self._lock:
            self._subscribers.add(target)
        return target

    def unsubscribe(self, target: queue.Queue[Event]) -> None:
        with self._lock:
            self._subscribers.discard(target)

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.as_dict() for event in self._history]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()

    def clear_history_and_publish(self) -> Event:
        """Clear replay history and order the UI event under the same lock.

        A separate clear() then publish() leaves a gap where a new translation
        can be stored and subsequently erased by the browser's clear event.
        """
        event = Event("history_cleared")
        with self._lock:
            self._history.clear()
            self._fan_out_locked(event)
        return event
