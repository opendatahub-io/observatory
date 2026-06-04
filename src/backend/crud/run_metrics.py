import aiosqlite


async def get_run_metrics_summary(
    db: aiosqlite.Connection,
    pipeline_slug: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    where = ["1=1"]
    params: list = []

    if pipeline_slug:
        where.append("p.slug = ?")
        params.append(pipeline_slug)
    if since:
        where.append("r.started_at >= ?")
        params.append(since)
    if until:
        where.append("r.started_at <= ?")
        params.append(until)

    where_clause = " AND ".join(where)

    cursor = await db.execute(f"""
        SELECT
            COUNT(*) as total_runs,
            SUM(CASE WHEN r.status = 'success' THEN 1 ELSE 0 END) as success_count,
            AVG(r.duration_seconds) as avg_duration,
            AVG(CASE WHEN r.queued_at IS NOT NULL AND r.started_at IS NOT NULL
                THEN CAST((julianday(r.started_at) - julianday(r.queued_at)) * 86400 AS INTEGER)
                ELSE NULL END) as avg_queue_seconds
        FROM pipeline_runs r
        JOIN pipelines p ON p.id = r.pipeline_id
        WHERE {where_clause}
    """, params)
    row = await cursor.fetchone()
    d = dict(row)
    total = d["total_runs"] or 0
    success = d["success_count"] or 0
    return {
        "total_runs": total,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "avg_duration_seconds": round(d["avg_duration"] or 0),
        "avg_queue_seconds": round(d["avg_queue_seconds"] or 0),
    }


async def get_run_trends(
    db: aiosqlite.Connection,
    pipeline_slug: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    where = ["1=1"]
    params: list = []

    if pipeline_slug:
        where.append("p.slug = ?")
        params.append(pipeline_slug)
    if since:
        where.append("r.started_at >= ?")
        params.append(since)
    if until:
        where.append("r.started_at <= ?")
        params.append(until)

    where_clause = " AND ".join(where)

    cursor = await db.execute(f"""
        SELECT
            date(r.started_at) as day,
            COUNT(*) as run_count,
            AVG(r.duration_seconds) as avg_duration,
            AVG(CASE WHEN r.queued_at IS NOT NULL AND r.started_at IS NOT NULL
                THEN CAST((julianday(r.started_at) - julianday(r.queued_at)) * 86400 AS INTEGER)
                ELSE NULL END) as avg_queue_seconds,
            SUM(CASE WHEN r.status = 'success' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
        FROM pipeline_runs r
        JOIN pipelines p ON p.id = r.pipeline_id
        WHERE {where_clause} AND r.started_at IS NOT NULL
        GROUP BY day
        ORDER BY day
    """, params)
    rows = await cursor.fetchall()
    return [
        {
            "date": r["day"],
            "run_count": r["run_count"],
            "avg_duration": round(r["avg_duration"] or 0),
            "avg_queue_seconds": round(r["avg_queue_seconds"] or 0),
            "success_rate": round(r["success_rate"] or 0, 1),
        }
        for r in rows
    ]


async def get_run_breakdown(
    db: aiosqlite.Connection,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    where = ["1=1"]
    params: list = []

    if since:
        where.append("r.started_at >= ?")
        params.append(since)
    if until:
        where.append("r.started_at <= ?")
        params.append(until)

    where_clause = " AND ".join(where)

    cursor = await db.execute(f"""
        SELECT
            p.slug,
            p.name as pipeline_name,
            COUNT(*) as total_runs,
            SUM(CASE WHEN r.status = 'success' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
            AVG(r.duration_seconds) as avg_duration,
            MAX(r.duration_seconds) as max_duration,
            AVG(CASE WHEN r.queued_at IS NOT NULL AND r.started_at IS NOT NULL
                THEN CAST((julianday(r.started_at) - julianday(r.queued_at)) * 86400 AS INTEGER)
                ELSE NULL END) as avg_queue_seconds
        FROM pipeline_runs r
        JOIN pipelines p ON p.id = r.pipeline_id
        WHERE {where_clause}
        GROUP BY p.id
        ORDER BY total_runs DESC
    """, params)
    rows = await cursor.fetchall()
    return [
        {
            "slug": r["slug"],
            "pipeline_name": r["pipeline_name"],
            "total_runs": r["total_runs"],
            "success_rate": round(r["success_rate"] or 0, 1),
            "avg_duration": round(r["avg_duration"] or 0),
            "max_duration": r["max_duration"] or 0,
            "avg_queue_seconds": round(r["avg_queue_seconds"] or 0),
        }
        for r in rows
    ]
