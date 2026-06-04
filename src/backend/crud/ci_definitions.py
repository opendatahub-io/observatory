import aiosqlite


async def get_pipeline_ci_jobs(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM ci_jobs WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    jobs = [dict(r) for r in await cursor.fetchall()]

    for job in jobs:
        jid = job["id"]

        cursor = await db.execute("SELECT tag FROM ci_job_tags WHERE job_id = ?", (jid,))
        job["tags"] = [r["tag"] for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT key, value, masked FROM ci_job_variables WHERE job_id = ? ORDER BY key",
            (jid,),
        )
        job["variables"] = [dict(r) for r in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT phase, step_order, command FROM ci_job_scripts WHERE job_id = ? ORDER BY phase, step_order",
            (jid,),
        )
        job["scripts"] = [dict(r) for r in await cursor.fetchall()]

    return jobs


async def get_pipeline_ci_includes(db: aiosqlite.Connection, pipeline_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM ci_includes WHERE pipeline_id = ? ORDER BY id",
        (pipeline_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_image_inventory(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("""
        SELECT j.image, GROUP_CONCAT(DISTINCT p.slug) as pipelines, COUNT(*) as job_count
        FROM ci_jobs j
        JOIN pipelines p ON p.id = j.pipeline_id
        WHERE j.image IS NOT NULL AND j.image != ''
        GROUP BY j.image
        ORDER BY job_count DESC
    """)
    rows = await cursor.fetchall()
    return [
        {"image": r["image"], "pipelines": r["pipelines"].split(","), "job_count": r["job_count"]}
        for r in rows
    ]


async def get_tag_inventory(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("""
        SELECT t.tag, GROUP_CONCAT(DISTINCT p.slug) as pipelines, COUNT(*) as job_count
        FROM ci_job_tags t
        JOIN ci_jobs j ON j.id = t.job_id
        JOIN pipelines p ON p.id = j.pipeline_id
        GROUP BY t.tag
        ORDER BY job_count DESC
    """)
    rows = await cursor.fetchall()
    return [
        {"tag": r["tag"], "pipelines": r["pipelines"].split(","), "job_count": r["job_count"]}
        for r in rows
    ]
