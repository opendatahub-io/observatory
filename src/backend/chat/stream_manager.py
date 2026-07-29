"""In-process pub/sub registry for live chat generations.

A chat response is produced by a background task (decoupled from the HTTP
request that started it) so that a client disconnecting — browser refresh,
navigating away, a dropped tab — never aborts generation or loses the answer.
Each active generation owns a :class:`StreamSession` that any number of
subscribers can follow: the original POST, a reconnect via
``GET /conversations/{id}/stream``, or a second tab. Late joiners get the full
replay buffer first, then live events.

The registry is intentionally in-memory and single-process. It pairs with the
persist-in-``finally`` logic in ``routers/chat.py``: the assistant message is
written to the DB before the session is removed, so a client that just missed
the live stream can still load the saved answer.
"""

from __future__ import annotations

import asyncio

# Sentinel pushed to each subscriber queue when a generation completes so the
# subscribe() generator knows to stop awaiting.
_SENTINEL = object()


class StreamSession:
    """Fan-out for a single in-flight generation, keyed by conversation.

    ``publish`` and ``finish`` are synchronous (no ``await``) so they cannot
    interleave with ``subscribe``'s buffer snapshot under asyncio's cooperative
    scheduling — that is what guarantees a late subscriber neither drops nor
    duplicates an event across the replay/live boundary.
    """

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.buffer: list[str] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.done = asyncio.Event()

    def publish(self, sse: str) -> None:
        """Record an SSE chunk and fan it out to all live subscribers."""
        self.buffer.append(sse)
        for queue in self.subscribers:
            queue.put_nowait(sse)

    def finish(self) -> None:
        """Mark the generation complete and unblock every subscriber."""
        self.done.set()
        for queue in self.subscribers:
            queue.put_nowait(_SENTINEL)

    async def subscribe(self):
        """Yield the replay buffer, then live events until the generation ends.

        The snapshot + registration below run with no ``await`` between them, so
        no ``publish`` can slip in and be lost or double-delivered.
        """
        replay = list(self.buffer)
        queue: asyncio.Queue | None = None
        if not self.done.is_set():
            queue = asyncio.Queue()
            self.subscribers.add(queue)

        try:
            for chunk in replay:
                yield chunk
            if queue is None:
                return
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            if queue is not None:
                self.subscribers.discard(queue)


# Active generations keyed by conversation_id.
_active: dict[str, StreamSession] = {}

# Strong references to background generation tasks so they are not
# garbage-collected mid-flight (asyncio only holds weak references).
_pending_tasks: set[asyncio.Task] = set()


def get_session(conversation_id: str) -> StreamSession | None:
    return _active.get(conversation_id)


def register_session(conversation_id: str) -> StreamSession:
    session = StreamSession(conversation_id)
    _active[conversation_id] = session
    return session


def remove_session(conversation_id: str) -> None:
    _active.pop(conversation_id, None)


def track_task(task: asyncio.Task) -> None:
    """Hold a reference to a background task until it completes."""
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def cancel_all_tasks() -> None:
    """Cancel any in-flight generation tasks (best-effort, for shutdown)."""
    tasks = list(_pending_tasks)
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
