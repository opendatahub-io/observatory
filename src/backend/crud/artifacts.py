import aiosqlite


async def list_run_artifacts(db: aiosqlite.Connection, run_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT id, source, source_ref, file_path, file_size, mime_type, created_at
        FROM job_artifacts
        WHERE pipeline_run_id = ?
        ORDER BY source, file_path
        """,
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_artifact_content(db: aiosqlite.Connection, artifact_id: int) -> dict | None:
    cursor = await db.execute(
        "SELECT id, file_path, file_size, mime_type, content FROM job_artifacts WHERE id = ?",
        (artifact_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_pipeline_latest_artifacts(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT a.id, a.source, a.source_ref, a.file_path, a.file_size, a.mime_type, a.created_at
        FROM job_artifacts a
        WHERE a.pipeline_run_id = (
            SELECT id FROM pipeline_runs
            WHERE pipeline_id = ?
            ORDER BY started_at DESC
            LIMIT 1
        )
        ORDER BY a.source, a.file_path
        """,
        (pipeline_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
