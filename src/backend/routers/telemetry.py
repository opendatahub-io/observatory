from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from backend.database import get_db
from backend.crud.telemetry_dimensions import get_all_dimension_summaries
from backend.crud.run_metrics import (
    get_run_metrics_summary,
    get_run_trends,
    get_run_breakdown,
)
from backend.crud.telemetry import (
    get_telemetry_summary as crud_get_telemetry_summary,
    get_telemetry_trends as crud_get_telemetry_trends,
    get_cost_breakdown as crud_get_cost_breakdown,
    get_pipeline_telemetry as crud_get_pipeline_telemetry,
)
from backend.schemas.telemetry import (
    TelemetrySummaryResponse,
    TelemetryTrendsResponse,
    TelemetryTrendPoint,
    CostBreakdownResponse,
    CostBreakdownItem,
    PipelineTelemetryResponse,
    PipelineTelemetryRow,
)

router = APIRouter(tags=["telemetry"])


@router.get("/api/telemetry/summary", response_model=TelemetrySummaryResponse)
async def telemetry_summary(
    pipeline: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    result = await crud_get_telemetry_summary(
        db, pipeline_slug=pipeline, since=since, until=until
    )
    return TelemetrySummaryResponse(
        pipeline_slug=pipeline,
        **result,
    )


@router.get("/api/telemetry/trends", response_model=TelemetryTrendsResponse)
async def telemetry_trends(
    pipeline: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    rows = await crud_get_telemetry_trends(
        db, pipeline_slug=pipeline, since=since, until=until
    )
    return TelemetryTrendsResponse(
        trends=[TelemetryTrendPoint(**r) for r in rows],
    )


@router.get("/api/telemetry/cost", response_model=CostBreakdownResponse)
async def telemetry_cost_breakdown(
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    rows = await crud_get_cost_breakdown(db, since=since, until=until)
    return CostBreakdownResponse(
        breakdown=[CostBreakdownItem(**r) for r in rows],
    )


@router.get(
    "/api/pipelines/{slug}/telemetry",
    response_model=PipelineTelemetryResponse,
)
async def pipeline_telemetry(
    slug: str,
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    result = await crud_get_pipeline_telemetry(
        db, pipeline_slug=slug, since=since, until=until
    )
    return PipelineTelemetryResponse(
        pipeline_slug=result["pipeline_slug"],
        rows=[PipelineTelemetryRow(**r) for r in result["rows"]],
        total_tokens=result["total_tokens"],
        total_cost=result["total_cost"],
        run_count=result["run_count"],
    )


@router.get("/api/telemetry/run-metrics")
async def run_metrics_summary(
    pipeline: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_run_metrics_summary(db, pipeline_slug=pipeline, since=since, until=until)


@router.get("/api/telemetry/run-trends")
async def run_trends(
    pipeline: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_run_trends(db, pipeline_slug=pipeline, since=since, until=until)


@router.get("/api/telemetry/run-breakdown")
async def run_breakdown(
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_run_breakdown(db, since=since, until=until)


@router.get("/api/telemetry/dimensions")
async def telemetry_dimensions(
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_all_dimension_summaries(db)
