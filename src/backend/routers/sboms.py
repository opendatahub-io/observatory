from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import require_api_key

from backend.database import get_db
from backend.crud.sboms import (
    upsert_sbom,
    list_sboms as crud_list_sboms,
    get_sbom_by_digest,
    get_vulnerabilities_for_digest,
    get_vulnerability_summary,
)
from backend.schemas.sboms import (
    SBOMCreate,
    SBOMDetail,
    SBOMListItem,
    VulnerabilityResponse,
    VulnerabilitySummaryItem,
)

router = APIRouter(prefix="/api/sboms", tags=["sboms"])
provenance_vuln_router = APIRouter(prefix="/api/provenance", tags=["sboms"])


@router.post("", status_code=201, response_model=SBOMDetail, dependencies=[Depends(require_api_key)])
async def push_sbom(
    payload: SBOMCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    data = payload.model_dump()
    row = await upsert_sbom(db, data)
    return SBOMDetail(**row)


@router.get("", response_model=list[SBOMListItem])
async def list_sboms_endpoint(
    db: aiosqlite.Connection = Depends(get_db),
):
    rows = await crud_list_sboms(db)
    return [SBOMListItem(**r) for r in rows]


@router.get("/{digest:path}/vulnerabilities", response_model=list[VulnerabilityResponse])
async def get_sbom_vulnerabilities(
    digest: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    # Verify the SBOM exists
    sbom = await get_sbom_by_digest(db, digest)
    if sbom is None:
        raise HTTPException(status_code=404, detail="SBOM not found")
    vulns = await get_vulnerabilities_for_digest(db, digest)
    return [VulnerabilityResponse(**v) for v in vulns]


@router.get("/{digest:path}", response_model=SBOMDetail)
async def get_sbom(
    digest: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    row = await get_sbom_by_digest(db, digest)
    if row is None:
        raise HTTPException(status_code=404, detail="SBOM not found")
    return SBOMDetail(**row)


@provenance_vuln_router.get(
    "/vulnerabilities", response_model=list[VulnerabilitySummaryItem]
)
async def vulnerability_summary(
    severity: Optional[str] = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
):
    rows = await get_vulnerability_summary(db, severity=severity)
    return [VulnerabilitySummaryItem(**r) for r in rows]
