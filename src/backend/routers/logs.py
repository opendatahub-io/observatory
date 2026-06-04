import asyncio
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.logging_handler import log_handler

router = APIRouter(prefix="/api/admin/logs", tags=["logs"])


@router.get("")
async def get_logs(
    level: str | None = Query(None),
    since: float | None = Query(None),
):
    return log_handler.get_entries(level=level, since=since)


@router.get("/stream")
async def stream_logs():
    """SSE endpoint for real-time log tailing."""
    q = log_handler.subscribe()

    async def event_generator():
        try:
            while True:
                entry = await q.get()
                data = json.dumps(entry)
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            log_handler.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
