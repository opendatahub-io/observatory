"""CRUD operations for scoped API keys."""

import hashlib
import json
import secrets
from datetime import datetime, timezone

import aiosqlite


async def create_api_key(
    db: aiosqlite.Connection,
    name: str,
    scopes: list[str],
    expires_at: datetime | None = None,
) -> tuple[dict, str]:
    """Generate a new API key, store its hash, and return (row_dict, plaintext_key)."""
    raw_key = "obs_" + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]  # "obs_" + first 8 hex chars
    scopes_json = json.dumps(scopes)

    expires_at_str = expires_at.isoformat() if expires_at else None

    cursor = await db.execute(
        """INSERT INTO api_keys (key_hash, key_prefix, name, scopes, expires_at)
           VALUES (?, ?, ?, ?, ?)""",
        (key_hash, key_prefix, name, scopes_json, expires_at_str),
    )
    await db.commit()

    row_id = cursor.lastrowid
    # Fetch the created row
    cursor = await db.execute(
        "SELECT id, key_prefix, name, scopes, created_at, expires_at, last_used_at, is_active "
        "FROM api_keys WHERE id = ?",
        (row_id,),
    )
    row = await cursor.fetchone()
    row_dict = {
        "id": row["id"],
        "key_prefix": row["key_prefix"],
        "name": row["name"],
        "scopes": json.loads(row["scopes"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_used_at": row["last_used_at"],
        "is_active": bool(row["is_active"]),
    }
    return row_dict, raw_key


async def list_api_keys(db: aiosqlite.Connection) -> list[dict]:
    """Return all API keys (prefix only, no full key or hash)."""
    cursor = await db.execute(
        "SELECT id, key_prefix, name, scopes, created_at, expires_at, last_used_at, is_active "
        "FROM api_keys ORDER BY created_at DESC"
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "key_prefix": row["key_prefix"],
            "name": row["name"],
            "scopes": json.loads(row["scopes"]),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "last_used_at": row["last_used_at"],
            "is_active": bool(row["is_active"]),
        }
        for row in rows
    ]


async def revoke_api_key(db: aiosqlite.Connection, key_id: int) -> bool:
    """Set is_active=FALSE for the given key. Returns True if a row was updated."""
    cursor = await db.execute(
        "UPDATE api_keys SET is_active = FALSE WHERE id = ?", (key_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


async def validate_api_key(
    db: aiosqlite.Connection,
    raw_key: str,
    pipeline_slug: str | None = None,
) -> bool:
    """Hash the key, look up in DB, check active/expiry/scope. Update last_used_at on success."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    cursor = await db.execute(
        "SELECT id, scopes, expires_at, is_active FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    )
    row = await cursor.fetchone()
    if row is None:
        return False

    if not row["is_active"]:
        return False

    # Check expiry
    if row["expires_at"]:
        try:
            expires = datetime.fromisoformat(row["expires_at"])
            # Make it timezone-aware if not already
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now > expires:
                return False
        except (ValueError, TypeError):
            pass

    # Check scope
    if pipeline_slug is not None:
        scopes = json.loads(row["scopes"])
        if "*" not in scopes and pipeline_slug not in scopes:
            return False

    # Update last_used_at
    await db.execute(
        "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), row["id"]),
    )
    await db.commit()
    return True


async def has_any_api_keys(db: aiosqlite.Connection) -> bool:
    """Return True if there are any API keys in the database."""
    cursor = await db.execute("SELECT COUNT(*) FROM api_keys")
    row = await cursor.fetchone()
    return row[0] > 0
