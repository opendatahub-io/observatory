import json

import aiosqlite

from backend.schemas.pipelines import PipelineCreate, PipelineUpdate


def _deserialize_json_fields(row_dict: dict) -> dict:
    """Deserialize jobs and job_patterns from JSON strings to lists."""
    for field in ("jobs", "job_patterns"):
        val = row_dict.get(field)
        if val is not None:
            row_dict[field] = json.loads(val)
    return row_dict


async def list_pipelines(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("SELECT * FROM pipelines ORDER BY COALESCE(display_order, 9999), id")
    rows = await cursor.fetchall()
    return [_deserialize_json_fields(dict(row)) for row in rows]


async def get_pipeline(db: aiosqlite.Connection, slug: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM pipelines WHERE slug = ?", (slug,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return _deserialize_json_fields(dict(row))


async def create_pipeline(db: aiosqlite.Connection, data: PipelineCreate) -> dict:
    jobs_json = json.dumps(data.jobs) if data.jobs is not None else None
    job_patterns_json = json.dumps(data.job_patterns) if data.job_patterns is not None else None
    await db.execute(
        """
        INSERT INTO pipelines (slug, name, description, owner, repo_url, platform,
                               platform_project_id, cron, expected_interval_minutes,
                               timeout_minutes, status, "group", display_order,
                               jobs, job_patterns)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.slug,
            data.name,
            data.description,
            data.owner,
            data.repo_url,
            data.platform,
            data.platform_project_id,
            data.cron,
            data.expected_interval_minutes,
            data.timeout_minutes,
            data.status,
            data.group,
            data.display_order,
            jobs_json,
            job_patterns_json,
        ),
    )
    await db.commit()
    return await get_pipeline(db, data.slug)


async def update_pipeline(
    db: aiosqlite.Connection, slug: str, data: PipelineUpdate
) -> dict | None:
    existing = await get_pipeline(db, slug)
    if existing is None:
        return None

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        return existing

    set_clauses = []
    values = []
    for field, value in updates.items():
        # Serialize list fields as JSON for storage
        if field in ("jobs", "job_patterns") and value is not None:
            value = json.dumps(value)
        # Quote "group" since it's a SQL keyword
        col_name = f'"{field}"' if field == "group" else field
        set_clauses.append(f"{col_name} = ?")
        values.append(value)

    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    values.append(slug)

    await db.execute(
        f"UPDATE pipelines SET {', '.join(set_clauses)} WHERE slug = ?",
        values,
    )
    await db.commit()

    # If slug was updated, use the new slug to fetch
    new_slug = updates.get("slug", slug)
    return await get_pipeline(db, new_slug)


async def delete_pipeline(db: aiosqlite.Connection, slug: str) -> bool:
    existing = await get_pipeline(db, slug)
    if existing is None:
        return False
    pid = existing["id"]
    await db.execute("DELETE FROM collector_state WHERE pipeline_id = ?", (pid,))
    await db.execute("DELETE FROM mlflow_experiments WHERE pipeline_id = ?", (pid,))
    await db.execute("DELETE FROM pipelines WHERE slug = ?", (slug,))
    await db.commit()
    return True
