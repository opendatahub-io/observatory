"""CRUD helpers for the collector_state table."""

from datetime import datetime, timezone

import aiosqlite


async def get_collector_states(db: aiosqlite.Connection) -> list[dict]:
    """Return all collector states joined with pipeline name/slug."""
    cursor = await db.execute(
        """
        SELECT
            cs.id,
            cs.pipeline_id,
            p.name   AS pipeline_name,
            p.slug   AS pipeline_slug,
            cs.last_collected_at,
            cs.last_run_external_id,
            cs.last_error,
            cs.consecutive_failures
        FROM collector_state cs
        JOIN pipelines p ON p.id = cs.pipeline_id
        ORDER BY p.slug
        """
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_collector_state(db: aiosqlite.Connection, pipeline_id: int) -> dict | None:
    """Return collector state for a single pipeline, or None."""
    cursor = await db.execute(
        "SELECT * FROM collector_state WHERE pipeline_id = ?",
        (pipeline_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def upsert_collector_state(db: aiosqlite.Connection, pipeline_id: int, **kwargs) -> None:
    """Create or update the collector_state row for a pipeline.

    Accepted kwargs: last_collected_at, last_run_external_id,
    last_error, consecutive_failures.
    """
    existing = await get_collector_state(db, pipeline_id)

    if existing is None:
        cols = ["pipeline_id"]
        vals: list = [pipeline_id]
        for key in ("last_collected_at", "last_run_external_id", "last_error", "consecutive_failures"):
            if key in kwargs:
                cols.append(key)
                vals.append(kwargs[key])
        placeholders = ", ".join("?" for _ in cols)
        col_str = ", ".join(cols)
        await db.execute(
            f"INSERT INTO collector_state ({col_str}) VALUES ({placeholders})",
            vals,
        )
    else:
        if not kwargs:
            return
        set_parts = []
        vals = []
        for key, value in kwargs.items():
            set_parts.append(f"{key} = ?")
            vals.append(value)
        vals.append(pipeline_id)
        await db.execute(
            f"UPDATE collector_state SET {', '.join(set_parts)} WHERE pipeline_id = ?",
            vals,
        )

    await db.commit()
