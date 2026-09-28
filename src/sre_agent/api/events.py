"""In-process event broker for live incident streaming.

The agent runs in a worker thread while FastAPI serves from the event loop, so publishing
has to hop threads safely. Subscribers get an asyncio.Queue per client; a slow client is
dropped rather than allowed to block the agent.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

from ..logging_setup import get_logger
from ..models import ExecutionEvent

log = get_logger("events")

_MAX_QUEUE = 500


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recent: deque[dict[str, Any]] = deque(maxlen=300)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the serving event loop so worker threads can publish into it."""
        self._loop = loop

    # ── subscription ────────────────────────────────────────
    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ── publishing ──────────────────────────────────────────
    def publish(self, payload: dict[str, Any]) -> None:
        """Publish from any thread."""
        self._recent.append(payload)
        loop, subscribers = self._loop, list(self._subscribers)
        if loop is None or not subscribers:
            return
        if loop.is_closed():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is loop:
            self._deliver(payload, subscribers)
        else:
            loop.call_soon_threadsafe(self._deliver, payload, subscribers)

    def _deliver(
        self, payload: dict[str, Any], subscribers: list[asyncio.Queue[dict[str, Any]]]
    ) -> None:
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("dropping a slow event subscriber")
                self._subscribers.discard(queue)

    def publish_event(self, event: ExecutionEvent) -> None:
        payload = event.model_dump(mode="json")
        payload["_type"] = "event"
        self.publish(payload)

    # ── history ─────────────────────────────────────────────
    def recent(self, incident_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        items = [
            item
            for item in self._recent
            if incident_id is None or item.get("incident_id") == incident_id
        ]
        return items[-limit:]

    @staticmethod
    def sse(payload: dict[str, Any]) -> str:
        """Format one Server-Sent Event frame."""
        return f"data: {json.dumps(payload, default=str)}\n\n"
