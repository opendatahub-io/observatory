"""API key authentication for push endpoints."""

import hashlib
import json

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

import backend.config
from backend.database import get_db
from backend.crud.api_keys import validate_api_key as _validate_api_key, has_any_api_keys

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    api_key: str | None = Security(api_key_header),
    db=Depends(get_db),
):
    """Validate the X-API-Key header.

    1. If no key provided and no auth configured (no DB keys AND no env key), allow.
    2. If key provided, try DB lookup first (validate_api_key with no scope check).
    3. If DB lookup fails, fall back to env var check (OBSERVATORY_API_KEY).
    4. If nothing matches, return 401.
    """
    env_key = backend.config.settings.api_key
    db_has_keys = await has_any_api_keys(db)

    if not api_key:
        # No key provided — only allow if no auth is configured at all
        if not env_key and not db_has_keys:
            return
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Key provided — try DB first
    if await _validate_api_key(db, api_key):
        return

    # Fall back to env var check
    if env_key and api_key == env_key:
        return

    raise HTTPException(status_code=401, detail="Invalid API key")


async def require_api_key_scoped(
    pipeline_slug: str | None,
    api_key: str | None,
    db,
) -> None:
    """Validate the X-API-Key header with scope checking against pipeline_slug.

    Same logic as require_api_key but passes pipeline_slug to validate_api_key
    for scope checking. A 403 is raised if the key is valid but lacks scope.
    """
    env_key = backend.config.settings.api_key
    db_has_keys = await has_any_api_keys(db)

    if not api_key:
        if not env_key and not db_has_keys:
            return
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Key provided — try DB with scope check
    if await _validate_api_key(db, api_key, pipeline_slug=pipeline_slug):
        return

    # The key might be valid but lack scope — check without scope to distinguish 401 vs 403
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    cursor = await db.execute(
        "SELECT scopes, is_active FROM api_keys WHERE key_hash = ?", (key_hash,)
    )
    row = await cursor.fetchone()
    if row and row["is_active"]:
        # Key exists and is active but scope check failed
        scopes = json.loads(row["scopes"])
        if "*" not in scopes and pipeline_slug not in scopes:
            raise HTTPException(
                status_code=403,
                detail=f"API key does not have scope for pipeline '{pipeline_slug}'",
            )

    # Fall back to env var check (env var key has implicit wildcard scope)
    if env_key and api_key == env_key:
        return

    raise HTTPException(status_code=401, detail="Invalid API key")
