"""Query endpoints for OTEL log records and metric points."""

from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from backend.database import get_db
from backend.crud.otel import (
    get_otel_log_summary,
    get_otel_logs,
    get_otel_log_detail,
    get_otel_metric_summary,
    get_otel_metric_names,
    get_otel_metric_series,
)

router = APIRouter(prefix="/api", tags=["otel-explorer"])


@router.get("/otel/logs/summary")
async def otel_log_summary(
    pipeline: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_otel_log_summary(
        db, pipeline_slug=pipeline, since=since, until=until
    )


@router.get("/otel/logs")
async def otel_logs(
    pipeline_run_id: Optional[int] = Query(default=None),
    trace_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_otel_logs(
        db,
        pipeline_run_id=pipeline_run_id,
        trace_id=trace_id,
        severity=severity,
        search=search,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/otel/logs/{log_id}")
async def otel_log_detail(log_id: int, db: aiosqlite.Connection = Depends(get_db)):
    result = await get_otel_log_detail(db, log_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Log record not found")
    return result


@router.get("/otel/metrics/summary")
async def otel_metric_summary(
    pipeline: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_otel_metric_summary(
        db, pipeline_slug=pipeline, since=since, until=until
    )


@router.get("/otel/metrics/names")
async def otel_metric_names(db: aiosqlite.Connection = Depends(get_db)):
    return await get_otel_metric_names(db)


@router.get("/otel/metrics/series")
async def otel_metric_series(
    metric_name: str = Query(...),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_otel_metric_series(
        db, metric_name=metric_name, since=since, until=until
    )
