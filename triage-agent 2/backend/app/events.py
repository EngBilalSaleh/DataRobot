"""Per-ticket event broker: flow steps (running in worker threads) publish, SSE clients subscribe.

The Flow emits explicitly from each step rather than hooking framework internals, which
keeps the stream predictable. History is kept so a client that connects late replays
everything it missed.
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict


class EventBroker:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._history: dict[int, list[dict]] = defaultdict(list)
        self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def reset(self, ticket_id: int) -> None:
        with self._lock:
            self._history.pop(ticket_id, None)

    def publish(self, ticket_id: int, event: dict) -> None:
        with self._lock:
            self._history[ticket_id].append(event)
            queues = list(self._subscribers.get(ticket_id, ()))
        if self._loop is None:
            return
        for q in queues:
            self._loop.call_soon_threadsafe(q.put_nowait, event)

    def subscribe(self, ticket_id: int) -> tuple[asyncio.Queue, list[dict]]:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers[ticket_id].add(q)
            history = list(self._history.get(ticket_id, []))
        return q, history

    def unsubscribe(self, ticket_id: int, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers[ticket_id].discard(q)

    def has_history(self, ticket_id: int) -> bool:
        with self._lock:
            return bool(self._history.get(ticket_id))


broker = EventBroker()
