"""CRUD for the repository registry.

``repositories`` is a derived/synced index over the repo_url references on
pipelines/skills/shared-libs (see database.py backfill + upsert hooks). This
module also exposes the operator-facing operations: manual registration,
status/branch overrides, delete (blocked while links remain), and recording
sync outcomes.
"""

from pathlib import Path

import aiosqlite

import backend.config


def _with_checkout_path(row: dict) -> dict:
    """Attach the derived on-disk checkout path to a repository row."""
    root = backend.config.settings.checkout_root
    row["checkout_path"] = str(
        Path(root) / row["domain"] / row["owner"] / row["name"]
    )
    return row


async def list_repositories(
    db: aiosqlite.Connection,
    status: str | None = None,
    kind: str | None = None,
) -> list[dict]:
    query = "SELECT * FROM repositories"
    clauses = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY domain, owner, name"
    cursor = await db.execute(query, params)
    return [_with_checkout_path(dict(r)) for r in await cursor.fetchall()]


async def get_repository(db: aiosqlite.Connection, repo_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,))
    row = await cursor.fetchone()
    return _with_checkout_path(dict(row)) if row else None


async def get_repository_by_triple(
    db: aiosqlite.Connection, domain: str, owner: str, name: str
) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM repositories WHERE domain = ? AND owner = ? AND name = ?",
        (domain, owner, name),
    )
    row = await cursor.fetchone()
    return _with_checkout_path(dict(row)) if row else None


async def get_linked_pipelines(db: aiosqlite.Connection, repo_id: int) -> list[dict]:
    cursor = await db.execute(
        """SELECT l.pipeline_id, l.relation, l.purpose, l.branch,
                  p.slug, p.name
           FROM pipeline_repository_links l
           JOIN pipelines p ON p.id = l.pipeline_id
           WHERE l.repository_id = ?
           ORDER BY l.relation, p.slug""",
        (repo_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def count_links(db: aiosqlite.Connection, repo_id: int) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) AS n FROM pipeline_repository_links WHERE repository_id = ?",
        (repo_id,),
    )
    return (await cursor.fetchone())["n"]


async def create_repository(db: aiosqlite.Connection, data: dict) -> dict:
    """Manually register a repository. Raises aiosqlite.IntegrityError on a
    duplicate (domain, owner, name)."""
    cursor = await db.execute(
        """INSERT INTO repositories
           (domain, owner, name, kind, git_url, description, status, default_branch)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["domain"],
            data["owner"],
            data["name"],
            data["kind"],
            data["git_url"],
            data.get("description"),
            data.get("status", "active"),
            data.get("default_branch", "main"),
        ),
    )
    await db.commit()
    return await get_repository(db, cursor.lastrowid)


async def update_repository(
    db: aiosqlite.Connection, repo_id: int, data: dict
) -> dict | None:
    """Update operator-editable fields (description, status, default_branch)."""
    fields = []
    params: list = []
    for key in ("description", "status", "default_branch"):
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            params.append(data[key])
    if not fields:
        return await get_repository(db, repo_id)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(repo_id)
    cursor = await db.execute(
        f"UPDATE repositories SET {', '.join(fields)} WHERE id = ?", params
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_repository(db, repo_id)


async def delete_repository(db: aiosqlite.Connection, repo_id: int) -> bool:
    """Deregister a repository. Caller must ensure no links remain."""
    cursor = await db.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    await db.commit()
    return cursor.rowcount > 0


async def record_sync_result(
    db: aiosqlite.Connection, repo_id: int, status: str, error: str | None
) -> None:
    """Record the outcome of a sync attempt for observability."""
    await db.execute(
        """UPDATE repositories
           SET last_synced_at = CURRENT_TIMESTAMP,
               last_sync_status = ?,
               last_sync_error = ?
           WHERE id = ?""",
        (status, error, repo_id),
    )
    await db.commit()
