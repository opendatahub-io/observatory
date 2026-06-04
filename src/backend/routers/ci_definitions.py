import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from backend.crud.ci_definitions import (
    get_pipeline_ci_jobs,
    get_pipeline_ci_includes,
    get_image_inventory,
    get_tag_inventory,
)
from backend.database import get_db
from backend.schemas.ci_definitions import (
    CIDefinitionResponse,
    CIJobResponse,
    CIIncludeResponse,
    ImageInventoryItem,
    TagInventoryItem,
)

router = APIRouter(prefix="/api", tags=["ci-definitions"])


@router.get("/pipelines/{slug}/ci-jobs", response_model=CIDefinitionResponse)
async def get_pipeline_ci_definition(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT id FROM pipelines WHERE slug = ?", (slug,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline_id = dict(row)["id"]
    jobs = await get_pipeline_ci_jobs(db, pipeline_id)
    includes = await get_pipeline_ci_includes(db, pipeline_id)

    return CIDefinitionResponse(
        jobs=[CIJobResponse(**j) for j in jobs],
        includes=[CIIncludeResponse(**i) for i in includes],
    )


@router.get("/ci-jobs/images", response_model=list[ImageInventoryItem])
async def list_images(db: aiosqlite.Connection = Depends(get_db)):
    return [ImageInventoryItem(**i) for i in await get_image_inventory(db)]


@router.get("/ci-jobs/tags", response_model=list[TagInventoryItem])
async def list_tags(db: aiosqlite.Connection = Depends(get_db)):
    return [TagInventoryItem(**t) for t in await get_tag_inventory(db)]
