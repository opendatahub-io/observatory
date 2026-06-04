import aiosqlite


async def get_trace_summary(db: aiosqlite.Connection) -> dict:
    cursor = await db.execute("SELECT COUNT(*) FROM trace_events")
    total_events = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(DISTINCT pipeline_run_id) FROM trace_events")
    runs_with_traces = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM trace_packages")
    total_packages = (await cursor.fetchone())[0]

    cursor = await db.execute("""
        SELECT event_type, COUNT(*) as cnt FROM trace_events GROUP BY event_type ORDER BY cnt DESC
    """)
    by_type = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("""
        SELECT source, COUNT(*) as cnt FROM trace_events GROUP BY source
    """)
    by_source = [dict(r) for r in await cursor.fetchall()]

    return {
        "total_events": total_events,
        "runs_with_traces": runs_with_traces,
        "total_packages": total_packages,
        "events_by_type": by_type,
        "events_by_source": by_source,
    }


async def get_run_trace_events(
    db: aiosqlite.Connection,
    run_id: int,
    event_type: str | None = None,
    source: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    where = ["pipeline_run_id = ?"]
    params: list = [run_id]

    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    if source:
        where.append("source = ?")
        params.append(source)

    where_clause = " AND ".join(where)

    cursor = await db.execute(f"SELECT COUNT(*) FROM trace_events WHERE {where_clause}", params)
    total = (await cursor.fetchone())[0]

    cursor = await db.execute(f"""
        SELECT id, source, event_type, timestamp, content, line_number
        FROM trace_events WHERE {where_clause}
        ORDER BY COALESCE(line_number, id)
        LIMIT ? OFFSET ?
    """, params + [limit, offset])
    events = [dict(r) for r in await cursor.fetchall()]

    return {"events": events, "total": total}


async def get_run_trace_summary(db: aiosqlite.Connection, run_id: int) -> dict:
    cursor = await db.execute("""
        SELECT event_type, source, COUNT(*) as cnt
        FROM trace_events WHERE pipeline_run_id = ?
        GROUP BY event_type, source ORDER BY cnt DESC
    """, (run_id,))
    event_counts = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("""
        SELECT manager, name, version, arch, repo
        FROM trace_packages WHERE pipeline_run_id = ?
        ORDER BY manager, name
    """, (run_id,))
    packages = [dict(r) for r in await cursor.fetchall()]

    cursor = await db.execute("""
        SELECT key, value FROM trace_metadata WHERE pipeline_run_id = ?
    """, (run_id,))
    metadata = {r["key"]: r["value"] for r in await cursor.fetchall()}

    return {
        "event_counts": event_counts,
        "packages": packages,
        "metadata": metadata,
    }


async def get_run_packages(db: aiosqlite.Connection, run_id: int) -> list[dict]:
    cursor = await db.execute("""
        SELECT manager, name, version, arch, repo
        FROM trace_packages WHERE pipeline_run_id = ?
        ORDER BY manager, name
    """, (run_id,))
    return [dict(r) for r in await cursor.fetchall()]


async def get_tool_usage_summary(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("""
        SELECT
            CASE WHEN source = 'otel' THEN
                json_extract(content, '$.tool_name')
            ELSE
                json_extract(content, '$.tool')
            END as tool_name,
            COUNT(*) as call_count,
            COUNT(DISTINCT pipeline_run_id) as run_count
        FROM trace_events
        WHERE event_type IN ('tool_call', 'tool_result')
        GROUP BY tool_name
        HAVING tool_name IS NOT NULL
        ORDER BY call_count DESC
    """)
    return [dict(r) for r in await cursor.fetchall()]


async def get_package_inventory(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("""
        SELECT manager, name, GROUP_CONCAT(DISTINCT version) as versions,
            COUNT(DISTINCT pipeline_run_id) as run_count
        FROM trace_packages
        GROUP BY manager, name
        ORDER BY run_count DESC, name
    """)
    return [dict(r) for r in await cursor.fetchall()]
