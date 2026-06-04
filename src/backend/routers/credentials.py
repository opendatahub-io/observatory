"""Admin endpoints for managing platform credentials."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.crud.credentials import (
    create_credential,
    list_credentials,
    update_credential,
    revoke_credential,
    test_credential,
)
from backend.schemas.credentials import (
    CredentialCreate,
    CredentialListItem,
    CredentialUpdate,
    CredentialTestResult,
)

router = APIRouter(prefix="/api/admin/credentials", tags=["admin"])


@router.post("", status_code=201, response_model=CredentialListItem)
async def create_cred(
    body: CredentialCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Create a new platform credential. The token is encrypted at rest."""
    row_dict = await create_credential(
        db,
        body.name,
        body.platform,
        body.base_url,
        body.token,
        body.scopes,
        body.expires_at,
    )
    return CredentialListItem(**row_dict)


@router.get("", response_model=list[CredentialListItem])
async def list_creds(
    db: aiosqlite.Connection = Depends(get_db),
):
    """List all platform credentials (no tokens exposed)."""
    rows = await list_credentials(db)
    return [CredentialListItem(**r) for r in rows]


@router.put("/{cred_id}", response_model=CredentialListItem)
async def update_cred(
    cred_id: int,
    body: CredentialUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Update a platform credential."""
    result = await update_credential(
        db,
        cred_id,
        name=body.name,
        token=body.token,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return CredentialListItem(**result)


@router.delete("/{cred_id}", status_code=204)
async def revoke_cred(
    cred_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Revoke a platform credential (sets is_active=FALSE)."""
    updated = await revoke_credential(db, cred_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Credential not found")
    return None


@router.post("/{cred_id}/test", response_model=CredentialTestResult)
async def test_cred(
    cred_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Test a platform credential by making a lightweight API call."""
    result = await test_credential(db, cred_id)
    return CredentialTestResult(**result)
