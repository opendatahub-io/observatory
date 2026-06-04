"""CRUD operations for platform credentials with Fernet encryption."""

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiosqlite
import httpx
from cryptography.fernet import Fernet

import backend.config

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the configured credential key.

    If ``credential_key`` is set, use it directly (must be a valid 32-byte
    URL-safe base64 Fernet key).  Otherwise derive one from ``api_key`` via
    SHA-256.  Raises ``RuntimeError`` if neither is available.
    """
    credential_key = backend.config.settings.credential_key
    if credential_key:
        return Fernet(credential_key.encode())

    api_key = backend.config.settings.api_key
    if api_key:
        derived = base64.urlsafe_b64encode(hashlib.sha256(api_key.encode()).digest())
        return Fernet(derived)

    raise RuntimeError(
        "No encryption key available. Set OBSERVATORY_CREDENTIAL_KEY "
        "(a valid Fernet key) or OBSERVATORY_API_KEY."
    )


def encrypt_token(token: str) -> str:
    """Encrypt a plaintext token and return the ciphertext as a string."""
    f = _get_fernet()
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a Fernet-encrypted token string."""
    f = _get_fernet()
    return f.decrypt(encrypted_token.encode()).decode()


async def create_credential(
    db: aiosqlite.Connection,
    name: str,
    platform: str,
    base_url: str,
    token: str,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> dict:
    """Encrypt token, store credential, and return the row (no token)."""
    encrypted = encrypt_token(token)
    scopes_json = json.dumps(scopes or ["*"])
    expires_at_str = expires_at.isoformat() if expires_at else None

    cursor = await db.execute(
        """INSERT INTO platform_credentials
           (name, platform, base_url, encrypted_token, scopes, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, platform, base_url, encrypted, scopes_json, expires_at_str),
    )
    await db.commit()

    row_id = cursor.lastrowid
    cursor = await db.execute(
        "SELECT id, name, platform, base_url, scopes, created_at, expires_at, "
        "last_used_at, is_active FROM platform_credentials WHERE id = ?",
        (row_id,),
    )
    row = await cursor.fetchone()
    return _row_to_dict(row)


async def list_credentials(db: aiosqlite.Connection) -> list[dict]:
    """Return all credentials (metadata only, no decrypted tokens)."""
    cursor = await db.execute(
        "SELECT id, name, platform, base_url, scopes, created_at, expires_at, "
        "last_used_at, is_active FROM platform_credentials ORDER BY created_at DESC"
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


async def update_credential(
    db: aiosqlite.Connection,
    cred_id: int,
    **kwargs,
) -> dict | None:
    """Update credential fields.  If ``token`` is provided, re-encrypt it."""
    # Verify exists
    cursor = await db.execute(
        "SELECT id FROM platform_credentials WHERE id = ?", (cred_id,)
    )
    if not await cursor.fetchone():
        return None

    updates: list[str] = []
    params: list = []

    if "name" in kwargs and kwargs["name"] is not None:
        updates.append("name = ?")
        params.append(kwargs["name"])

    if "token" in kwargs and kwargs["token"] is not None:
        updates.append("encrypted_token = ?")
        params.append(encrypt_token(kwargs["token"]))

    if "scopes" in kwargs and kwargs["scopes"] is not None:
        updates.append("scopes = ?")
        params.append(json.dumps(kwargs["scopes"]))

    if "expires_at" in kwargs:
        updates.append("expires_at = ?")
        ea = kwargs["expires_at"]
        params.append(ea.isoformat() if ea else None)

    if not updates:
        # Nothing to update; return the existing row
        cursor = await db.execute(
            "SELECT id, name, platform, base_url, scopes, created_at, expires_at, "
            "last_used_at, is_active FROM platform_credentials WHERE id = ?",
            (cred_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(row)

    params.append(cred_id)
    await db.execute(
        f"UPDATE platform_credentials SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT id, name, platform, base_url, scopes, created_at, expires_at, "
        "last_used_at, is_active FROM platform_credentials WHERE id = ?",
        (cred_id,),
    )
    row = await cursor.fetchone()
    return _row_to_dict(row)


async def revoke_credential(db: aiosqlite.Connection, cred_id: int) -> bool:
    """Set is_active=FALSE for the given credential.  Returns True if updated."""
    cursor = await db.execute(
        "UPDATE platform_credentials SET is_active = FALSE WHERE id = ?",
        (cred_id,),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_credential_for_pipeline(
    db: aiosqlite.Connection,
    pipeline: dict,
) -> str | None:
    """Resolve the best credential for a pipeline.

    Resolution order:
    1. Match ``platform`` to the pipeline's platform
    2. Match ``base_url`` hostname to the hostname in the pipeline's ``repo_url``
    3. Check ``scopes`` includes the pipeline slug or ``["*"]``
    4. Must be active and not expired
    5. Decrypt and return the token
    6. Update ``last_used_at``
    """
    platform = pipeline.get("platform", "")
    repo_url = pipeline.get("repo_url", "")
    slug = pipeline.get("slug", "")

    if not platform or not repo_url:
        return None

    repo_host = urlparse(repo_url).netloc

    now = datetime.now(timezone.utc).isoformat()

    cursor = await db.execute(
        """SELECT id, base_url, scopes, encrypted_token
           FROM platform_credentials
           WHERE platform = ?
             AND is_active = TRUE
             AND (expires_at IS NULL OR expires_at > ?)
           ORDER BY created_at DESC""",
        (platform, now),
    )
    rows = await cursor.fetchall()

    # Score candidates: prefer matching base_url host
    best_id: int | None = None
    best_token: str | None = None
    best_score: int = -1

    for row in rows:
        row_dict = dict(row)
        cred_base_url = row_dict["base_url"]
        cred_host = urlparse(cred_base_url).netloc

        scopes = json.loads(row_dict["scopes"])

        # Check scope match
        if "*" not in scopes and slug not in scopes:
            continue

        score = 0
        # Host match gives higher score
        if cred_host == repo_host:
            score += 10

        if score > best_score:
            best_score = score
            best_id = row_dict["id"]
            best_token = row_dict["encrypted_token"]

    if best_token is None:
        return None

    # Decrypt the token
    try:
        token = decrypt_token(best_token)
    except Exception:
        logger.error("Failed to decrypt credential id=%s", best_id)
        return None

    # Update last_used_at
    await db.execute(
        "UPDATE platform_credentials SET last_used_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), best_id),
    )
    await db.commit()

    return token


async def test_credential(
    db: aiosqlite.Connection,
    cred_id: int,
) -> dict:
    """Decrypt the credential and make a lightweight API call to verify it works.

    Returns ``{"success": bool, "message": str}``.
    """
    cursor = await db.execute(
        "SELECT platform, base_url, encrypted_token, is_active "
        "FROM platform_credentials WHERE id = ?",
        (cred_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return {"success": False, "message": "Credential not found"}

    row_dict = dict(row)
    if not row_dict["is_active"]:
        return {"success": False, "message": "Credential is revoked"}

    try:
        token = decrypt_token(row_dict["encrypted_token"])
    except Exception as exc:
        return {"success": False, "message": f"Decryption failed: {exc}"}

    platform = row_dict["platform"]
    base_url = row_dict["base_url"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if platform == "gitlab":
                resp = await client.get(
                    f"{base_url}/api/v4/user",
                    headers={"PRIVATE-TOKEN": token},
                )
            elif platform == "github":
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
            else:
                return {"success": False, "message": f"Unsupported platform: {platform}"}

            if resp.status_code == 200:
                return {"success": True, "message": "Credential is valid"}
            else:
                return {
                    "success": False,
                    "message": f"API returned HTTP {resp.status_code}",
                }
    except httpx.HTTPError as exc:
        return {"success": False, "message": f"Connection error: {exc}"}


def _row_to_dict(row) -> dict:
    """Convert an aiosqlite.Row to a dict for CredentialListItem."""
    return {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"],
        "base_url": row["base_url"],
        "scopes": json.loads(row["scopes"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_used_at": row["last_used_at"],
        "is_active": bool(row["is_active"]),
    }
