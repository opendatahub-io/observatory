import aiosqlite


async def get_telemetry_summary(
    db: aiosqlite.Connection,
    pipeline_slug: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Return aggregated telemetry totals across pipelines or for one pipeline."""
    conditions: list[str] = []
    params: list = []

    if pipeline_slug is not None:
        conditions.append("p.slug = ?")
        params.append(pipeline_slug)
    if since is not None:
        conditions.append("pr.started_at >= ?")
        params.append(since)
    if until is not None:
        conditions.append("pr.started_at <= ?")
        params.append(until)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT
            COALESCE(SUM(ts.total_tokens), 0) AS total_tokens,
            COALESCE(SUM(ts.input_tokens), 0) AS input_tokens,
            COALESCE(SUM(ts.output_tokens), 0) AS output_tokens,
            COALESCE(SUM(ts.cost_usd), 0.0) AS total_cost,
            COUNT(DISTINCT pr.id) AS run_count
        FROM telemetry_summaries ts
        JOIN pipeline_runs pr ON ts.pipeline_run_id = pr.id
        JOIN pipelines p ON pr.pipeline_id = p.id
        {where}
    """

    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    return dict(row)


async def get_telemetry_trends(
    db: aiosqlite.Connection,
    pipeline_slug: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Return time-series data grouped by day."""
    conditions: list[str] = []
    params: list = []

    if pipeline_slug is not None:
        conditions.append("p.slug = ?")
        params.append(pipeline_slug)
    if since is not None:
        conditions.append("pr.started_at >= ?")
        params.append(since)
    if until is not None:
        conditions.append("pr.started_at <= ?")
        params.append(until)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT
            DATE(pr.started_at) AS date,
            COALESCE(SUM(ts.total_tokens), 0) AS total_tokens,
            COALESCE(SUM(ts.cost_usd), 0.0) AS cost_usd,
            COUNT(DISTINCT pr.id) AS run_count
        FROM telemetry_summaries ts
        JOIN pipeline_runs pr ON ts.pipeline_run_id = pr.id
        JOIN pipelines p ON pr.pipeline_id = p.id
        {where}
        GROUP BY DATE(pr.started_at)
        ORDER BY date ASC
    """

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_cost_breakdown(
    db: aiosqlite.Connection,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Return cost grouped by pipeline, model, and skill."""
    conditions: list[str] = []
    params: list = []

    if since is not None:
        conditions.append("pr.started_at >= ?")
        params.append(since)
    if until is not None:
        conditions.append("pr.started_at <= ?")
        params.append(until)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT
            p.slug AS pipeline_slug,
            p.name AS pipeline_name,
            ts.model,
            ts.skill_name,
            COALESCE(SUM(ts.cost_usd), 0.0) AS total_cost,
            COALESCE(SUM(ts.total_tokens), 0) AS total_tokens,
            COUNT(DISTINCT pr.id) AS run_count
        FROM telemetry_summaries ts
        JOIN pipeline_runs pr ON ts.pipeline_run_id = pr.id
        JOIN pipelines p ON pr.pipeline_id = p.id
        {where}
        GROUP BY p.slug, p.name, ts.model, ts.skill_name
        ORDER BY total_cost DESC
    """

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_pipeline_telemetry(
    db: aiosqlite.Connection,
    pipeline_slug: str,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    """Return telemetry rows for a specific pipeline along with summary."""
    conditions = ["p.slug = ?"]
    params: list = [pipeline_slug]

    if since is not None:
        conditions.append("pr.started_at >= ?")
        params.append(since)
    if until is not None:
        conditions.append("pr.started_at <= ?")
        params.append(until)

    where = " WHERE " + " AND ".join(conditions)

    # Individual rows
    rows_query = f"""
        SELECT
            ts.id,
            ts.pipeline_run_id,
            ts.total_tokens,
            ts.input_tokens,
            ts.output_tokens,
            ts.cost_usd,
            ts.model,
            ts.skill_name,
            ts.duration_ms,
            ts.source,
            ts.created_at,
            pr.external_id AS run_external_id,
            pr.started_at AS run_started_at
        FROM telemetry_summaries ts
        JOIN pipeline_runs pr ON ts.pipeline_run_id = pr.id
        JOIN pipelines p ON pr.pipeline_id = p.id
        {where}
        ORDER BY pr.started_at DESC
    """

    cursor = await db.execute(rows_query, params)
    rows = await cursor.fetchall()

    # Summary
    summary_query = f"""
        SELECT
            COALESCE(SUM(ts.total_tokens), 0) AS total_tokens,
            COALESCE(SUM(ts.cost_usd), 0.0) AS total_cost,
            COUNT(DISTINCT pr.id) AS run_count
        FROM telemetry_summaries ts
        JOIN pipeline_runs pr ON ts.pipeline_run_id = pr.id
        JOIN pipelines p ON pr.pipeline_id = p.id
        {where}
    """

    summary_cursor = await db.execute(summary_query, params)
    summary = await summary_cursor.fetchone()

    return {
        "pipeline_slug": pipeline_slug,
        "rows": [dict(row) for row in rows],
        "total_tokens": summary["total_tokens"],
        "total_cost": summary["total_cost"],
        "run_count": summary["run_count"],
    }
