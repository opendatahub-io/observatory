import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend.crud.artifacts import list_run_artifacts, get_artifact_content, list_pipeline_latest_artifacts
from backend.database import get_db
from backend.schemas.artifacts import ArtifactFileResponse, ArtifactListResponse

router = APIRouter(prefix="/api", tags=["artifacts"])


@router.get("/pipelines/{slug}/runs/{run_id}/artifacts", response_model=ArtifactListResponse)
async def get_run_artifacts(slug: str, run_id: int, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT id FROM pipelines WHERE slug = ?", (slug,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    artifacts = await list_run_artifacts(db, run_id)
    return ArtifactListResponse(
        artifacts=[ArtifactFileResponse(**a) for a in artifacts],
        total=len(artifacts),
    )


@router.get("/artifacts/{artifact_id}/content")
async def get_artifact_file_content(artifact_id: int, db: aiosqlite.Connection = Depends(get_db)):
    artifact = await get_artifact_content(db, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = artifact.get("content")
    if content is None:
        raise HTTPException(status_code=404, detail="Artifact content not available")

    mime = artifact.get("mime_type") or "application/octet-stream"
    return Response(content=content, media_type=mime)


@router.get("/pipelines/{slug}/artifacts/latest", response_model=ArtifactListResponse)
async def get_latest_artifacts(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT id FROM pipelines WHERE slug = ?", (slug,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline_id = dict(row)["id"]
    artifacts = await list_pipeline_latest_artifacts(db, pipeline_id)
    return ArtifactListResponse(
        artifacts=[ArtifactFileResponse(**a) for a in artifacts],
        total=len(artifacts),
    )
