import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.database import get_db
from backend.crud.pipeline_metadata import (
    _resolve_pipeline_id,
    # images
    list_images,
    create_image,
    delete_image,
    # skills
    list_skills,
    create_skill,
    delete_skill,
    # shared libs
    list_shared_libs,
    create_shared_lib,
    delete_shared_lib,
    # jira contracts
    list_jira_contracts,
    create_jira_contract,
    delete_jira_contract,
    # telemetry config
    list_telemetry_config,
    create_telemetry_config,
    delete_telemetry_config,
    # artifact config
    list_artifact_config,
    create_artifact_config,
    delete_artifact_config,
)
from backend.schemas.pipeline_metadata import (
    PipelineImageCreate,
    PipelineImageResponse,
    PipelineSkillCreate,
    PipelineSkillResponse,
    PipelineSharedLibCreate,
    PipelineSharedLibResponse,
    PipelineJiraContractCreate,
    PipelineJiraContractResponse,
    PipelineTelemetryConfigCreate,
    PipelineTelemetryConfigResponse,
    PipelineArtifactConfigCreate,
    PipelineArtifactConfigResponse,
)

router = APIRouter(prefix="/api/pipelines", tags=["pipeline-metadata"])


async def _get_pipeline_id_or_404(db: aiosqlite.Connection, slug: str) -> int:
    pid = await _resolve_pipeline_id(db, slug)
    if pid is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pid


# ---- Images ----

@router.get("/{slug}/images", response_model=list[PipelineImageResponse])
async def list_pipeline_images(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await list_images(db, pid)


@router.post("/{slug}/images", response_model=PipelineImageResponse, status_code=201)
async def add_pipeline_image(
    slug: str, data: PipelineImageCreate, db: aiosqlite.Connection = Depends(get_db)
):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await create_image(db, pid, data.model_dump())


@router.delete("/{slug}/images/{resource_id}", status_code=204)
async def remove_pipeline_image(
    slug: str, resource_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    await _get_pipeline_id_or_404(db, slug)
    deleted = await delete_image(db, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(status_code=204)


# ---- Skills ----

@router.get("/{slug}/skills", response_model=list[PipelineSkillResponse])
async def list_pipeline_skills(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await list_skills(db, pid)


@router.post("/{slug}/skills", response_model=PipelineSkillResponse, status_code=201)
async def add_pipeline_skill(
    slug: str, data: PipelineSkillCreate, db: aiosqlite.Connection = Depends(get_db)
):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await create_skill(db, pid, data.model_dump())


@router.delete("/{slug}/skills/{resource_id}", status_code=204)
async def remove_pipeline_skill(
    slug: str, resource_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    await _get_pipeline_id_or_404(db, slug)
    deleted = await delete_skill(db, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    return Response(status_code=204)


# ---- Shared Libs ----

@router.get("/{slug}/shared-libs", response_model=list[PipelineSharedLibResponse])
async def list_pipeline_shared_libs(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await list_shared_libs(db, pid)


@router.post("/{slug}/shared-libs", response_model=PipelineSharedLibResponse, status_code=201)
async def add_pipeline_shared_lib(
    slug: str, data: PipelineSharedLibCreate, db: aiosqlite.Connection = Depends(get_db)
):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await create_shared_lib(db, pid, data.model_dump())


@router.delete("/{slug}/shared-libs/{resource_id}", status_code=204)
async def remove_pipeline_shared_lib(
    slug: str, resource_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    await _get_pipeline_id_or_404(db, slug)
    deleted = await delete_shared_lib(db, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Shared lib not found")
    return Response(status_code=204)


# ---- Jira Contracts ----

@router.get("/{slug}/jira-contracts", response_model=list[PipelineJiraContractResponse])
async def list_pipeline_jira_contracts(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await list_jira_contracts(db, pid)


@router.post("/{slug}/jira-contracts", response_model=PipelineJiraContractResponse, status_code=201)
async def add_pipeline_jira_contract(
    slug: str, data: PipelineJiraContractCreate, db: aiosqlite.Connection = Depends(get_db)
):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await create_jira_contract(db, pid, data.model_dump())


@router.delete("/{slug}/jira-contracts/{resource_id}", status_code=204)
async def remove_pipeline_jira_contract(
    slug: str, resource_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    await _get_pipeline_id_or_404(db, slug)
    deleted = await delete_jira_contract(db, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Jira contract not found")
    return Response(status_code=204)


# ---- Telemetry Config ----

@router.get("/{slug}/telemetry-config", response_model=list[PipelineTelemetryConfigResponse])
async def list_pipeline_telemetry_config(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await list_telemetry_config(db, pid)


@router.post("/{slug}/telemetry-config", response_model=PipelineTelemetryConfigResponse, status_code=201)
async def add_pipeline_telemetry_config(
    slug: str, data: PipelineTelemetryConfigCreate, db: aiosqlite.Connection = Depends(get_db)
):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await create_telemetry_config(db, pid, data.model_dump())


@router.delete("/{slug}/telemetry-config/{resource_id}", status_code=204)
async def remove_pipeline_telemetry_config(
    slug: str, resource_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    await _get_pipeline_id_or_404(db, slug)
    deleted = await delete_telemetry_config(db, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Telemetry config not found")
    return Response(status_code=204)


# ---- Artifact Config ----

@router.get("/{slug}/artifact-config", response_model=list[PipelineArtifactConfigResponse])
async def list_pipeline_artifact_config(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await list_artifact_config(db, pid)


@router.post("/{slug}/artifact-config", response_model=PipelineArtifactConfigResponse, status_code=201)
async def add_pipeline_artifact_config(
    slug: str, data: PipelineArtifactConfigCreate, db: aiosqlite.Connection = Depends(get_db)
):
    pid = await _get_pipeline_id_or_404(db, slug)
    return await create_artifact_config(db, pid, data.model_dump())


@router.delete("/{slug}/artifact-config/{resource_id}", status_code=204)
async def remove_pipeline_artifact_config(
    slug: str, resource_id: int, db: aiosqlite.Connection = Depends(get_db)
):
    await _get_pipeline_id_or_404(db, slug)
    deleted = await delete_artifact_config(db, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact config not found")
    return Response(status_code=204)
