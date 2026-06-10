"""Broker pub/sub in-process per gli aggiornamenti SSE verso il browser.

Una coda per sottoscrittore, per field_id. publish() non blocca mai:
se una coda è piena (client lento) l'evento viene scartato — alla
riconnessione il client rifà comunque il fetch completo dello stato.
"""
import asyncio
from collections import defaultdict

QUEUE_MAXSIZE = 200


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, field_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subscribers[field_id].add(queue)
        return queue

    def unsubscribe(self, field_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[field_id].discard(queue)
        if not self._subscribers[field_id]:
            del self._subscribers[field_id]

    def publish(self, field_id: str, event: str, data: dict) -> None:
        for queue in self._subscribers.get(field_id, set()):
            try:
                queue.put_nowait({"event": event, "data": data})
            except asyncio.QueueFull:
                pass


broker = EventBroker()
