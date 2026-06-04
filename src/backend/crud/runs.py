import aiosqlite


async def resolve_pipeline_id(db: aiosqlite.Connection, slug: str) -> int | None:
    """Look up a pipeline by slug and return its id, or None if not found."""
    cursor = await db.execute(
        "SELECT id FROM pipelines WHERE slug = ?", (slug,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return row["id"]


async def list_runs(
    db: aiosqlite.Connection,
    pipeline_id: int,
    page: int = 1,
    per_page: int = 20,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[list[dict], int]:
    """Return (runs, total_count) for a pipeline with optional filters."""
    conditions = ["pipeline_id = ?"]
    params: list = [pipeline_id]

    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if since is not None:
        conditions.append("started_at >= ?")
        params.append(since)
    if until is not None:
        conditions.append("started_at <= ?")
        params.append(until)

    where = " AND ".join(conditions)

    # Total count
    count_cursor = await db.execute(
        f"SELECT COUNT(*) as cnt FROM pipeline_runs WHERE {where}",
        params,
    )
    count_row = await count_cursor.fetchone()
    total = count_row["cnt"]

    # Paginated results
    offset = (page - 1) * per_page
    data_cursor = await db.execute(
        f"SELECT * FROM pipeline_runs WHERE {where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    )
    rows = await data_cursor.fetchall()

    return [dict(row) for row in rows], total


async def get_run(db: aiosqlite.Connection, run_id: int) -> dict | None:
    """Get a single run by its internal id."""
    cursor = await db.execute(
        "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)
