"""CRUD functions for querying OTEL log records and metric points."""

import json

import aiosqlite


async def get_otel_log_summary(
    db: aiosqlite.Connection,
    pipeline_slug: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    where = []
    params: list = []

    if pipeline_slug:
        where.append(
            "lr.pipeline_run_id IN (SELECT pr.id FROM pipeline_runs pr "
            "JOIN pipelines p ON p.id = pr.pipeline_id WHERE p.slug = ?)"
        )
        params.append(pipeline_slug)
    if since:
        where.append("lr.observed_at >= ?")
        params.append(since)
    if until:
        where.append("lr.observed_at <= ?")
        params.append(until)

    wc = " AND ".join(where) if where else "1=1"

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM otel_log_records lr WHERE {wc}", params
    )
    total = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"SELECT COUNT(DISTINCT lr.trace_id) FROM otel_log_records lr WHERE {wc} AND lr.trace_id IS NOT NULL",
        params,
    )
    distinct_traces = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM otel_log_records lr WHERE {wc} AND lr.observed_at >= datetime('now', '-1 day')",
        params,
    )
    recent_count = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"SELECT lr.severity_text, COUNT(*) as cnt FROM otel_log_records lr WHERE {wc} GROUP BY lr.severity_text ORDER BY cnt DESC",
        params,
    )
    by_severity = [dict(r) for r in await cursor.fetchall()]

    return {
        "total_logs": total,
        "distinct_traces": distinct_traces,
        "recent_count": recent_count,
        "by_severity": by_severity,
    }


async def get_otel_logs(
    db: aiosqlite.Connection,
    pipeline_run_id: int | None = None,
    trace_id: str | None = None,
    severity: str | None = None,
    search: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    where = []
    params: list = []

    if pipeline_run_id:
        where.append("pipeline_run_id = ?")
        params.append(pipeline_run_id)
    if trace_id:
        where.append("trace_id = ?")
        params.append(trace_id)
    if severity:
        where.append("severity_text = ?")
        params.append(severity)
    if search:
        where.append("(body LIKE ? OR attributes LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if since:
        where.append("observed_at >= ?")
        params.append(since)
    if until:
        where.append("observed_at <= ?")
        params.append(until)

    wc = " AND ".join(where) if where else "1=1"

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM otel_log_records WHERE {wc}", params
    )
    total = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"""SELECT id, pipeline_run_id, trace_id, span_id,
                   severity_number, severity_text, body,
                   attributes, resource_attrs, observed_at
            FROM otel_log_records
            WHERE {wc}
            ORDER BY observed_at DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    )
    logs = [dict(r) for r in await cursor.fetchall()]

    return {"logs": logs, "total": total}


async def get_otel_log_detail(
    db: aiosqlite.Connection, log_id: int
) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM otel_log_records WHERE id = ?", (log_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None

    result = dict(row)
    for field in ("attributes", "resource_attrs"):
        if result.get(field):
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


async def get_otel_metric_summary(
    db: aiosqlite.Connection,
    pipeline_slug: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    where = []
    params: list = []

    if pipeline_slug:
        where.append(
            "mp.pipeline_run_id IN (SELECT pr.id FROM pipeline_runs pr "
            "JOIN pipelines p ON p.id = pr.pipeline_id WHERE p.slug = ?)"
        )
        params.append(pipeline_slug)
    if since:
        where.append("mp.recorded_at >= ?")
        params.append(since)
    if until:
        where.append("mp.recorded_at <= ?")
        params.append(until)

    wc = " AND ".join(where) if where else "1=1"

    cursor = await db.execute(
        f"SELECT COUNT(DISTINCT mp.metric_name) FROM otel_metric_points mp WHERE {wc}",
        params,
    )
    distinct_metrics = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM otel_metric_points mp WHERE {wc}", params
    )
    total_points = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"""SELECT mp.metric_name, mp.metric_type, mp.value, mp.recorded_at
            FROM otel_metric_points mp
            WHERE mp.id IN (
                SELECT MAX(mp2.id) FROM otel_metric_points mp2
                WHERE {wc.replace('mp.', 'mp2.')}
                GROUP BY mp2.metric_name
            )
            ORDER BY mp.metric_name""",
        params,
    )
    latest_values = [dict(r) for r in await cursor.fetchall()]

    return {
        "distinct_metrics": distinct_metrics,
        "total_points": total_points,
        "latest_values": latest_values,
    }


async def get_otel_metric_names(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        """SELECT metric_name, metric_type,
                  COUNT(*) as point_count,
                  MAX(recorded_at) as last_recorded
           FROM otel_metric_points
           GROUP BY metric_name, metric_type
           ORDER BY point_count DESC"""
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_otel_metric_series(
    db: aiosqlite.Connection,
    metric_name: str,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    where = ["metric_name = ?"]
    params: list = [metric_name]

    if since:
        where.append("recorded_at >= ?")
        params.append(since)
    if until:
        where.append("recorded_at <= ?")
        params.append(until)

    wc = " AND ".join(where)

    cursor = await db.execute(
        f"""SELECT
                strftime('%Y-%m-%dT%H:00:00', recorded_at) as bucket,
                AVG(value) as avg_value,
                MAX(value) as max_value,
                MIN(value) as min_value,
                COUNT(*) as point_count
            FROM otel_metric_points
            WHERE {wc}
            GROUP BY bucket
            ORDER BY bucket ASC""",
        params,
    )
    return [dict(r) for r in await cursor.fetchall()]
