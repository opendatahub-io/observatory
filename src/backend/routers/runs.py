from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.database import get_db
from backend.crud.runs import (
    get_run as crud_get_run,
    list_runs as crud_list_runs,
    resolve_pipeline_id,
)
from backend.schemas.runs import RunListResponse, RunResponse

router = APIRouter(tags=["runs"])


@router.get("/api/pipelines/{slug}/runs", response_model=RunListResponse)
async def list_runs(
    slug: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    pipeline_id = await resolve_pipeline_id(db, slug)
    if pipeline_id is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    runs, total = await crud_list_runs(
        db,
        pipeline_id=pipeline_id,
        page=page,
        per_page=per_page,
        status=status,
        since=since,
        until=until,
    )
    return RunListResponse(
        runs=[RunResponse(**r) for r in runs],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/api/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    run = await crud_get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse(**run)
