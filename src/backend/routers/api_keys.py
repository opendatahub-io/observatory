"""Admin endpoints for managing scoped API keys."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.crud.api_keys import create_api_key, list_api_keys, revoke_api_key
from backend.schemas.api_keys import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyListItem

router = APIRouter(prefix="/api/admin/api-keys", tags=["admin"])


@router.post("", status_code=201, response_model=ApiKeyCreatedResponse)
async def create_key(
    body: ApiKeyCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Create a new API key. The plaintext key is returned only once."""
    row_dict, plaintext_key = await create_api_key(
        db, body.name, body.scopes, body.expires_at
    )
    return ApiKeyCreatedResponse(
        id=row_dict["id"],
        key=plaintext_key,
        key_prefix=row_dict["key_prefix"],
        name=row_dict["name"],
        scopes=row_dict["scopes"],
        created_at=row_dict["created_at"],
        expires_at=row_dict["expires_at"],
    )


@router.get("", response_model=list[ApiKeyListItem])
async def list_keys(
    db: aiosqlite.Connection = Depends(get_db),
):
    """List all API keys (prefix only, never full key)."""
    rows = await list_api_keys(db)
    return [ApiKeyListItem(**r) for r in rows]


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    """Revoke an API key (sets is_active=FALSE)."""
    updated = await revoke_api_key(db, key_id)
    if not updated:
        raise HTTPException(status_code=404, detail="API key not found")
    return None
