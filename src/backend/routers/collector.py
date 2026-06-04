"""API endpoints for collector status and manual trigger."""

import asyncio
import logging

import aiosqlite
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.database import get_db
from backend.collector.crud import get_collector_states
from backend.collector.scheduler import run_collector_cycle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collector", tags=["collector"])


@router.get("/status")
async def collector_status(db: aiosqlite.Connection = Depends(get_db)):
    """Return collector states for all pipelines."""
    states = await get_collector_states(db)
    return states


@router.post("/run")
async def trigger_collector_run(db: aiosqlite.Connection = Depends(get_db)):
    """Trigger a one-off collector cycle in the background. Returns 202 immediately."""
    asyncio.create_task(run_collector_cycle(db))
    return JSONResponse(
        status_code=202,
        content={"detail": "Collector cycle triggered"},
    )
