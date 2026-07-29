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


def _like_escape(term: str) -> str:
    """Escape LIKE wildcards so a raw search term matches literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_trace_content(
    db: aiosqlite.Connection,
    query: str,
    event_type: str | None = None,
    pipeline_slug: str | None = None,
    limit: int = 50,
) -> dict:
    """Search parsed trace events and raw job_trace logs for a free-text term.

    This is the missing "content search" path: given a token that only appears
    inside job output (e.g. a Jira key like ``RHAISTRAT-2364``), it resolves the
    pipeline runs that reference it. Returns a per-run rollup plus bounded sample
    matches (with snippets) from both ``trace_events`` and ``job_trace``
    artifact logs.
    """
    query = (query or "").strip()
    if not query:
        return {
            "query": query,
            "runs": [],
            "trace_matches": [],
            "artifact_matches": [],
            "run_count": 0,
            "total_run_count": 0,
            "match_count": 0,
            "truncated": False,
        }

    limit = max(1, min(int(limit or 50), 200))
    like = "%" + _like_escape(query) + "%"
    q_lower = query.lower()

    # --- accurate per-run counts (independent of the sample cap below) ---
    te_where = ["te.content LIKE ? ESCAPE '\\'"]
    te_params: list = [like]
    if event_type:
        te_where.append("te.event_type = ?")
        te_params.append(event_type)
    if pipeline_slug:
        te_where.append("p.slug = ?")
        te_params.append(pipeline_slug)
    te_clause = " AND ".join(te_where)

    cursor = await db.execute(
        f"""
        SELECT te.pipeline_run_id AS run_id, COUNT(*) AS cnt
        FROM trace_events te
        JOIN pipeline_runs pr ON pr.id = te.pipeline_run_id
        JOIN pipelines p ON p.id = pr.pipeline_id
        WHERE {te_clause}
        GROUP BY te.pipeline_run_id
        """,
        te_params,
    )
    te_counts: dict[int, int] = {r["run_id"]: r["cnt"] for r in await cursor.fetchall()}

    ja_counts: dict[int, int] = {}
    if not event_type:
        ja_where = [
            "ja.source = 'job_trace'",
            "CAST(ja.content AS TEXT) LIKE ? ESCAPE '\\'",
        ]
        ja_params: list = [like]
        if pipeline_slug:
            ja_where.append("p.slug = ?")
            ja_params.append(pipeline_slug)
        ja_clause = " AND ".join(ja_where)

        cursor = await db.execute(
            f"""
            SELECT ja.pipeline_run_id AS run_id, COUNT(*) AS cnt
            FROM job_artifacts ja
            JOIN pipeline_runs pr ON pr.id = ja.pipeline_run_id
            JOIN pipelines p ON p.id = pr.pipeline_id
            WHERE {ja_clause}
            GROUP BY ja.pipeline_run_id
            """,
            ja_params,
        )
        ja_counts = {r["run_id"]: r["cnt"] for r in await cursor.fetchall()}

    # --- per-run rollup (most-recent first, capped at `limit` runs) ---
    all_run_ids = set(te_counts) | set(ja_counts)
    runs: list[dict] = []
    if all_run_ids:
        placeholders = ",".join("?" for _ in all_run_ids)
        cursor = await db.execute(
            f"""
            SELECT pr.id AS run_id, p.slug AS pipeline_slug, pr.external_id,
                   pr.job, pr.status, pr.started_at, pr.web_url
            FROM pipeline_runs pr JOIN pipelines p ON p.id = pr.pipeline_id
            WHERE pr.id IN ({placeholders})
            ORDER BY pr.started_at DESC
            LIMIT ?
            """,
            list(all_run_ids) + [limit],
        )
        for r in await cursor.fetchall():
            d = dict(r)
            d["trace_event_matches"] = te_counts.get(d["run_id"], 0)
            d["artifact_matches"] = ja_counts.get(d["run_id"], 0)
            runs.append(d)

    # --- bounded sample matches (with snippets) for display ---
    cursor = await db.execute(
        f"""
        SELECT te.pipeline_run_id AS run_id, p.slug AS pipeline_slug,
               te.event_type, te.line_number,
               substr(te.content, 1, 300) AS snippet
        FROM trace_events te
        JOIN pipeline_runs pr ON pr.id = te.pipeline_run_id
        JOIN pipelines p ON p.id = pr.pipeline_id
        WHERE {te_clause}
        ORDER BY pr.started_at DESC, COALESCE(te.line_number, te.id)
        LIMIT ?
        """,
        te_params + [limit],
    )
    trace_matches = [{"kind": "trace_event", **dict(r)} for r in await cursor.fetchall()]

    artifact_matches: list[dict] = []
    if not event_type:
        cursor = await db.execute(
            f"""
            SELECT ja.id AS artifact_id, ja.pipeline_run_id AS run_id,
                   p.slug AS pipeline_slug, ja.file_path,
                   substr(CAST(ja.content AS TEXT),
                          MAX(1, instr(lower(CAST(ja.content AS TEXT)), ?) - 80),
                          300) AS snippet
            FROM job_artifacts ja
            JOIN pipeline_runs pr ON pr.id = ja.pipeline_run_id
            JOIN pipelines p ON p.id = pr.pipeline_id
            WHERE {ja_clause}
            ORDER BY ja.created_at DESC
            LIMIT ?
            """,
            [q_lower] + ja_params + [limit],
        )
        artifact_matches = [{"kind": "artifact", **dict(r)} for r in await cursor.fetchall()]

    return {
        "query": query,
        "runs": runs,
        "trace_matches": trace_matches,
        "artifact_matches": artifact_matches,
        "run_count": len(runs),
        "total_run_count": len(all_run_ids),
        "match_count": sum(te_counts.values()) + sum(ja_counts.values()),
        "truncated": len(all_run_ids) > len(runs),
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
