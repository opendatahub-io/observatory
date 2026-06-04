from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.database import get_db
from backend.crud.runs import resolve_pipeline_id
from backend.crud.provenance import (
    get_run_commands as crud_get_commands,
    get_run_containers as crud_get_containers,
    get_run_packages as crud_get_packages,
    get_run_provenance as crud_get_provenance,
    get_package_inventory as crud_get_package_inventory,
    get_container_inventory as crud_get_container_inventory,
)
from backend.schemas.provenance import (
    CommandResponse,
    ContainerInventoryResponse,
    ContainerResponse,
    PackageInventoryResponse,
    PackageResponse,
    RunProvenanceResponse,
    ContainerInventoryItem,
    PackageInventoryItem,
)

# Per-run provenance routes
run_router = APIRouter(tags=["provenance"])

# Cross-pipeline inventory routes
inventory_router = APIRouter(prefix="/api/provenance", tags=["provenance"])


async def _resolve_run(
    db: aiosqlite.Connection, slug: str, run_id: int
) -> int:
    """Verify the pipeline exists and the run belongs to it. Return run_id."""
    pipeline_id = await resolve_pipeline_id(db, slug)
    if pipeline_id is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    cursor = await db.execute(
        "SELECT id FROM pipeline_runs WHERE id = ? AND pipeline_id = ?",
        (run_id, pipeline_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_id


@run_router.get(
    "/api/pipelines/{slug}/runs/{run_id}/provenance",
    response_model=RunProvenanceResponse,
)
async def get_run_provenance(
    slug: str,
    run_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    await _resolve_run(db, slug, run_id)
    data = await crud_get_provenance(db, run_id)
    return RunProvenanceResponse(**data)


@run_router.get(
    "/api/pipelines/{slug}/runs/{run_id}/commands",
    response_model=list[CommandResponse],
)
async def get_run_commands(
    slug: str,
    run_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    await _resolve_run(db, slug, run_id)
    rows = await crud_get_commands(db, run_id)
    return [CommandResponse(**r) for r in rows]


@run_router.get(
    "/api/pipelines/{slug}/runs/{run_id}/packages",
    response_model=list[PackageResponse],
)
async def get_run_packages(
    slug: str,
    run_id: int,
    manager: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    await _resolve_run(db, slug, run_id)
    rows = await crud_get_packages(db, run_id, manager=manager)
    return [PackageResponse(**r) for r in rows]


@run_router.get(
    "/api/pipelines/{slug}/runs/{run_id}/containers",
    response_model=list[ContainerResponse],
)
async def get_run_containers(
    slug: str,
    run_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    await _resolve_run(db, slug, run_id)
    rows = await crud_get_containers(db, run_id)
    return [ContainerResponse(**r) for r in rows]


@inventory_router.get("/packages", response_model=PackageInventoryResponse)
async def package_inventory(db: aiosqlite.Connection = Depends(get_db)):
    items = await crud_get_package_inventory(db)
    return PackageInventoryResponse(
        packages=[PackageInventoryItem(**i) for i in items]
    )


@inventory_router.get("/containers", response_model=ContainerInventoryResponse)
async def container_inventory(db: aiosqlite.Connection = Depends(get_db)):
    items = await crud_get_container_inventory(db)
    return ContainerInventoryResponse(
        containers=[ContainerInventoryItem(**i) for i in items]
    )
