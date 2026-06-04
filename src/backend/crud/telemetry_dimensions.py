import aiosqlite


async def get_dimension_summary(
    db: aiosqlite.Connection,
    metric: str,
    dimension_key: str,
    pipeline_slug: str | None = None,
) -> list[dict]:
    where = ["d.metric = ?", "d.dimension_key = ?"]
    params: list = [metric, dimension_key]

    if pipeline_slug:
        where.append("p.slug = ?")
        params.append(pipeline_slug)

    where_clause = " AND ".join(where)

    cursor = await db.execute(f"""
        SELECT
            d.dimension_value,
            SUM(d.value) as total,
            COUNT(DISTINCT d.pipeline_run_id) as run_count
        FROM telemetry_dimensions d
        JOIN pipeline_runs r ON r.id = d.pipeline_run_id
        JOIN pipelines p ON p.id = r.pipeline_id
        WHERE {where_clause}
        GROUP BY d.dimension_value
        ORDER BY total DESC
    """, params)
    return [dict(r) for r in await cursor.fetchall()]


async def get_all_dimension_summaries(db: aiosqlite.Connection) -> dict:
    """Get all interesting dimension breakdowns in one call."""
    result = {}

    for metric, key, label in [
        ("claude_code.cost.usage", "model", "cost_by_model"),
        ("claude_code.cost.usage", "query_source", "cost_by_source"),
        ("claude_code.token.usage", "model", "tokens_by_model"),
        ("claude_code.token.usage", "type", "tokens_by_type"),
        ("claude_code.token.usage", "query_source", "tokens_by_source"),
        ("claude_code.lines_of_code.count", "type", "loc_by_type"),
    ]:
        result[label] = await get_dimension_summary(db, metric, key)

    return result
