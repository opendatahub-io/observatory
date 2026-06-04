from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from backend.crud.traces import (
    get_trace_summary,
    get_run_trace_events,
    get_run_trace_summary,
    get_run_packages,
    get_tool_usage_summary,
    get_package_inventory,
)
from backend.database import get_db

router = APIRouter(prefix="/api", tags=["traces"])


@router.get("/traces/summary")
async def trace_summary(db: aiosqlite.Connection = Depends(get_db)):
    return await get_trace_summary(db)


@router.get("/traces/tools")
async def tool_usage(db: aiosqlite.Connection = Depends(get_db)):
    return await get_tool_usage_summary(db)


@router.get("/traces/packages")
async def package_inventory(db: aiosqlite.Connection = Depends(get_db)):
    return await get_package_inventory(db)


@router.get("/pipelines/{slug}/runs/{run_id}/trace")
async def run_trace_events(
    slug: str,
    run_id: int,
    event_type: Optional[str] = Query(default=None, alias="type"),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_run_trace_events(db, run_id, event_type=event_type, source=source, limit=limit, offset=offset)


@router.get("/pipelines/{slug}/runs/{run_id}/trace/summary")
async def run_trace_summary(slug: str, run_id: int, db: aiosqlite.Connection = Depends(get_db)):
    return await get_run_trace_summary(db, run_id)


@router.get("/pipelines/{slug}/runs/{run_id}/trace/packages")
async def run_packages(slug: str, run_id: int, db: aiosqlite.Connection = Depends(get_db)):
    return await get_run_packages(db, run_id)
