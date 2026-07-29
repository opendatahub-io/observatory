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
    search_trace_content,
)
from backend.database import get_db

router = APIRouter(prefix="/api", tags=["traces"])


@router.get("/traces/summary")
async def trace_summary(db: aiosqlite.Connection = Depends(get_db)):
    return await get_trace_summary(db)


@router.get("/traces/search")
async def trace_search(
    q: str = Query(..., min_length=1, description="Free-text term to find in trace/artifact content"),
    event_type: Optional[str] = Query(default=None, alias="type"),
    pipeline: Optional[str] = Query(default=None, description="Restrict to a pipeline slug"),
    limit: int = Query(default=50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Full-text search over parsed trace events and raw job_trace logs.

    Resolves a token that only appears in job output (e.g. a Jira key) to the
    pipeline runs that reference it.
    """
    return await search_trace_content(
        db, q, event_type=event_type, pipeline_slug=pipeline, limit=limit
    )


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


@router.get("/traces/runs/{run_id}/events")
async def run_trace_events_by_id(
    run_id: int,
    event_type: Optional[str] = Query(default=None, alias="type"),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_run_trace_events(db, run_id, event_type=event_type, source=source, limit=limit, offset=offset)


@router.get("/traces/runs/{run_id}/summary")
async def run_trace_summary_by_id(run_id: int, db: aiosqlite.Connection = Depends(get_db)):
    return await get_run_trace_summary(db, run_id)


@router.get("/traces/runs/{run_id}/packages")
async def run_packages_by_id(run_id: int, db: aiosqlite.Connection = Depends(get_db)):
    return await get_run_packages(db, run_id)


@router.get("/traces/runs/{run_id}/logs")
async def run_trace_logs(run_id: int, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "SELECT id, file_path, file_size FROM job_artifacts WHERE source = 'job_trace' AND pipeline_run_id = ? ORDER BY file_path",
        (run_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]
