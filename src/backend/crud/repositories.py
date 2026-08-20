"""CRUD for the repository registry.

``repositories`` is a derived/synced index over the repo_url references on
pipelines/skills/shared-libs (see database.py backfill + upsert hooks). This
module also exposes the operator-facing operations: manual registration,
status/branch overrides, delete (blocked while links remain), and recording
sync outcomes.
"""

import mimetypes
import subprocess
from pathlib import Path

import aiosqlite

import backend.config
from backend.path_security import is_denied_path, validate_repo_path


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


# ---------------------------------------------------------------------------
# File browsing
# ---------------------------------------------------------------------------

_MAX_TREE_ENTRIES = 500
_MAX_BLOB_BYTES = 512 * 1024
_MAX_SEARCH_MATCHES = 200


def _repo_dir(repo: dict) -> Path:
    root = backend.config.settings.checkout_root
    return Path(root) / repo["domain"] / repo["owner"] / repo["name"]


def list_tree(repo: dict, rel_path: str) -> dict:
    """List directory entries at *rel_path* inside a repo checkout."""
    repo_dir = _repo_dir(repo)
    target = validate_repo_path(
        backend.config.settings.checkout_root, repo_dir, rel_path
    )
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {rel_path}")
    if not target.is_dir():
        raise NotADirectoryError(f"Not a directory: {rel_path}")

    entries = []
    truncated = False
    for child in sorted(target.iterdir()):
        if is_denied_path(child):
            continue
        if len(entries) >= _MAX_TREE_ENTRIES:
            truncated = True
            break
        entry = {
            "name": child.name,
            "type": "directory" if child.is_dir() else "file",
        }
        if child.is_file():
            try:
                entry["size"] = child.stat().st_size
            except OSError:
                entry["size"] = None
        entries.append(entry)

    display_path = rel_path if rel_path and rel_path != "." else "/"
    return {"path": display_path, "entries": entries, "truncated": truncated}


def read_blob(repo: dict, rel_path: str) -> dict:
    """Read file content at *rel_path* inside a repo checkout."""
    repo_dir = _repo_dir(repo)
    target = validate_repo_path(
        backend.config.settings.checkout_root, repo_dir, rel_path
    )
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {rel_path}")
    if target.is_dir():
        raise IsADirectoryError(f"Is a directory: {rel_path}. Use the tree endpoint.")

    size = target.stat().st_size
    truncated = size > _MAX_BLOB_BYTES
    raw = target.read_bytes()[:_MAX_BLOB_BYTES]

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"

    return {
        "path": rel_path,
        "size": size,
        "mime_type": mime,
        "content": content,
        "truncated": truncated,
    }


def search_files(repo: dict, pattern: str, glob: str | None = None) -> dict:
    """Grep for *pattern* across files in a repo checkout."""
    repo_dir = _repo_dir(repo)
    if not repo_dir.exists():
        raise FileNotFoundError("Repository has not been synced yet")

    cmd = [
        "git", "grep", "-n", "-I", "--no-color",
        "-e", pattern,
        "--max-count", "5",
    ]
    if glob:
        cmd.extend(["--", glob])

    try:
        result = subprocess.run(
            cmd, cwd=repo_dir, capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {"pattern": pattern, "matches": [], "truncated": True}

    matches = []
    truncated = False
    for line in result.stdout.splitlines():
        if len(matches) >= _MAX_SEARCH_MATCHES:
            truncated = True
            break
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, line_no, text = parts
        if is_denied_path(Path(file_path)):
            continue
        try:
            matches.append({
                "file": file_path,
                "line": int(line_no),
                "text": text.strip(),
            })
        except ValueError:
            continue

    return {"pattern": pattern, "matches": matches, "truncated": truncated}
