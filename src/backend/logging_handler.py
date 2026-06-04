import asyncio
import collections
import logging


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity=1000):
        super().__init__()
        self.buffer = collections.deque(maxlen=capacity)
        self._subscribers: list[asyncio.Queue] = []

    def emit(self, record):
        entry = {
            "timestamp": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }
        self.buffer.append(entry)
        # Push to all SSE subscribers
        for q in self._subscribers:
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def get_entries(self, level=None, since=None):
        entries = list(self.buffer)
        if level:
            entries = [e for e in entries if e["level"] == level.upper()]
        if since:
            entries = [e for e in entries if e["timestamp"] >= since]
        return entries

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass


# Module-level singleton
log_handler = RingBufferHandler(capacity=1000)
log_handler.setFormatter(logging.Formatter("%(message)s"))
log_handler.setLevel(logging.DEBUG)
