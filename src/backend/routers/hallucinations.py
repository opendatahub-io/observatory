from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query

from backend.crud.hallucinations import (
    get_hallucination_summary,
    get_claims_by_type,
    get_claims,
    get_claim_detail,
    get_pipeline_hallucination_summary,
    get_jira_key_claims,
)
from backend.database import get_db

router = APIRouter(prefix="/api", tags=["hallucinations"])


@router.get("/hallucinations/summary")
async def hallucination_summary(db: aiosqlite.Connection = Depends(get_db)):
    return await get_hallucination_summary(db)


@router.get("/hallucinations/by-type")
async def hallucination_by_type(db: aiosqlite.Connection = Depends(get_db)):
    return await get_claims_by_type(db)


@router.get("/hallucinations/claims")
async def list_claims(
    pipeline: Optional[str] = Query(default=None),
    claim_type: Optional[str] = Query(default=None, alias="type"),
    exclude_types: Optional[str] = Query(default=None),
    verdict: Optional[str] = Query(default=None),
    jira_key: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    sort: Optional[str] = Query(default=None),
    sort_dir: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    exclude_list = exclude_types.split(",") if exclude_types else None
    return await get_claims(
        db,
        pipeline_slug=pipeline,
        claim_type=claim_type,
        exclude_types=exclude_list,
        verdict=verdict,
        jira_key=jira_key,
        search=search,
        sort=sort,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.get("/hallucinations/claims/{claim_id}")
async def claim_detail(claim_id: int, db: aiosqlite.Connection = Depends(get_db)):
    result = await get_claim_detail(db, claim_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Claim not found")
    return result


@router.get("/hallucinations/claims/{claim_id}/log")
async def claim_verification_log(claim_id: int):
    from pathlib import Path
    from fastapi import HTTPException
    from fastapi.responses import Response
    log_path = Path("var/verification") / f"{claim_id}.md"
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Verification log not found")
    return Response(content=log_path.read_text(), media_type="text/markdown")


@router.get("/hallucinations/source-file")
async def source_file_content(path: str = Query(...)):
    from pathlib import Path
    from fastapi import HTTPException
    from fastapi.responses import Response
    # Prevent path traversal
    if ".." in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    file_path = Path("var/artifacts") / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Source file not found")
    return Response(content=file_path.read_text(errors="replace"), media_type="text/markdown")


@router.get("/pipelines/{slug}/hallucinations")
async def pipeline_hallucinations(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    return await get_pipeline_hallucination_summary(db, slug)


@router.get("/hallucinations/jira/{jira_key}")
async def jira_key_claims(jira_key: str, db: aiosqlite.Connection = Depends(get_db)):
    return await get_jira_key_claims(db, jira_key)
