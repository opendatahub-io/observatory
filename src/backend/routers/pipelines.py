import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.database import get_db
from backend.crud.pipelines import (
    create_pipeline as crud_create,
    delete_pipeline as crud_delete,
    get_pipeline as crud_get,
    list_pipelines as crud_list,
    update_pipeline as crud_update,
)
from backend.crud.pipeline_metadata import (
    list_images,
    list_skills,
    list_shared_libs,
    list_jira_contracts,
    list_telemetry_config,
    list_artifact_config,
)
from backend.schemas.pipelines import (
    PipelineCreate,
    PipelineListResponse,
    PipelineResponse,
    PipelineUpdate,
)
from backend.health import get_pipeline_health

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("", response_model=PipelineListResponse)
async def list_pipelines(db: aiosqlite.Connection = Depends(get_db)):
    rows = await crud_list(db)
    pipelines = []
    for row in rows:
        health = await get_pipeline_health(db, row)
        pipelines.append(PipelineResponse(**row, health=health))
    return PipelineListResponse(pipelines=pipelines)


@router.post("", response_model=PipelineResponse, status_code=201)
async def create_pipeline(
    data: PipelineCreate, db: aiosqlite.Connection = Depends(get_db)
):
    try:
        row = await crud_create(db, data)
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Pipeline slug already exists")
    return PipelineResponse(**row, health="grey")


@router.get("/{slug}", response_model=PipelineResponse)
async def get_pipeline(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    row = await crud_get(db, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    pid = row["id"]
    health = await get_pipeline_health(db, row)
    return PipelineResponse(
        **row,
        health=health,
        images=await list_images(db, pid),
        skills=await list_skills(db, pid),
        shared_libs=await list_shared_libs(db, pid),
        jira_contracts=await list_jira_contracts(db, pid),
        telemetry_config=await list_telemetry_config(db, pid),
        artifact_config=await list_artifact_config(db, pid),
    )


@router.put("/{slug}", response_model=PipelineResponse)
async def update_pipeline(
    slug: str, data: PipelineUpdate, db: aiosqlite.Connection = Depends(get_db)
):
    row = await crud_update(db, slug, data)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    health = await get_pipeline_health(db, row)
    return PipelineResponse(**row, health=health)


@router.delete("/{slug}", status_code=204)
async def delete_pipeline(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    deleted = await crud_delete(db, slug)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return Response(status_code=204)


@router.get("/{slug}/health")
async def pipeline_health(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    row = await crud_get(db, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    health = await get_pipeline_health(db, row)
    return {"slug": slug, "health": health}
