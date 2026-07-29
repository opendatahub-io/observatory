"""Derived index of Jira issue keys referenced in trace/artifact content.

Jira keys (e.g. ``RHAISTRAT-2364``) only appear inside job output — parsed
trace events and raw ``job_trace`` console logs — never in a structured column.
This module extracts those keys into the ``issue_references`` index so the
frontend can present a searchable list of issues without scanning ~700k trace
rows on every request.

A raw ``[A-Z][A-Z0-9]+-\\d+`` regex over trace content also matches code-ish
tokens (``FILTER-1``, ``CRUD-2``, placeholder ``RFE-001``). To keep the index to
real Jira issues we only accept keys whose *project prefix* is allow-listed. The
allow-list is derived from data the platform already treats as authoritative —
validated claim keys and declared pipeline Jira contracts — unioned with a small
curated default so it works before any claims exist.
"""

from __future__ import annotations

import re
from collections import Counter

import aiosqlite

# Project prefixes known to be real Jira projects for this deployment. The
# allow-list is augmented at runtime from the DB (see ``allowed_prefixes``).
DEFAULT_ALLOWED_PREFIXES = {"RHAISTRAT", "RHAIRFE", "RHOAIENG", "INFERENG"}

_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d+)\b")


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def allowed_prefixes(db: aiosqlite.Connection) -> set[str]:
    """Project prefixes considered real Jira projects.

    Curated default ∪ prefixes of validated claim keys ∪ declared contracts.
    """
    prefixes = set(DEFAULT_ALLOWED_PREFIXES)

    cursor = await db.execute(
        "SELECT DISTINCT jira_key FROM claim_jira_keys WHERE jira_key LIKE '%-%'"
    )
    for row in await cursor.fetchall():
        key = row[0] or ""
        prefix = key.split("-", 1)[0].strip().upper()
        if prefix:
            prefixes.add(prefix)

    cursor = await db.execute(
        "SELECT DISTINCT project FROM pipeline_jira_contracts "
        "WHERE project IS NOT NULL AND project != ''"
    )
    for row in await cursor.fetchall():
        prefixes.add(str(row[0]).strip().upper())

    return prefixes


def extract_keys(text: str | None, allowed: set[str]) -> Counter:
    """Return a Counter of allow-listed Jira keys found in ``text``."""
    counts: Counter = Counter()
    if not text:
        return counts
    for prefix, num in _JIRA_KEY_RE.findall(text):
        if prefix in allowed:
            counts[f"{prefix}-{num}"] += 1
    return counts


async def _index_rows(
    db: aiosqlite.Connection,
    allowed: set[str],
    query: str,
    params: tuple,
    source: str,
) -> tuple[dict[tuple[str, int], int], set[str], set[int]]:
    """Stream (run_id, content) rows, extracting keys. Returns
    ((key, run_id) -> count, distinct keys, distinct runs)."""
    agg: dict[tuple[str, int], int] = {}
    keys: set[str] = set()
    runs: set[int] = set()
    cursor = await db.execute(query, params)
    async for row in cursor:
        run_id = row[0]
        if run_id is None:
            continue
        for key, cnt in extract_keys(row[1], allowed).items():
            agg[(key, run_id)] = agg.get((key, run_id), 0) + cnt
            keys.add(key)
            runs.add(run_id)
    _ = source  # source is applied by the caller when inserting
    return agg, keys, runs


async def rebuild_issue_index(db: aiosqlite.Connection) -> dict:
    """Full rebuild of ``issue_references`` from all trace/artifact content.

    Operator-triggered; iterates row-by-row so memory stays bounded even though
    it touches hundreds of thousands of rows.
    """
    allowed = await allowed_prefixes(db)

    await db.execute("DELETE FROM issue_references")

    total_rows = 0
    all_keys: set[str] = set()
    all_runs: set[int] = set()

    for source, query, params in (
        (
            "trace_event",
            "SELECT pipeline_run_id, content FROM trace_events "
            "WHERE content GLOB '*-[0-9]*'",
            (),
        ),
        (
            "job_trace",
            "SELECT pipeline_run_id, CAST(content AS TEXT) FROM job_artifacts "
            "WHERE source = 'job_trace'",
            (),
        ),
    ):
        agg, keys, runs = await _index_rows(db, allowed, query, params, source)
        all_keys |= keys
        all_runs |= runs
        for (key, run_id), cnt in agg.items():
            await db.execute(
                "INSERT OR REPLACE INTO issue_references "
                "(jira_key, pipeline_run_id, source, match_count) VALUES (?,?,?,?)",
                (key, run_id, source, cnt),
            )
            total_rows += 1

    await db.commit()
    return {
        "keys": len(all_keys),
        "rows": total_rows,
        "runs": len(all_runs),
        "allowed_prefixes": sorted(allowed),
    }


async def index_run(db: aiosqlite.Connection, run_id: int) -> int:
    """Incrementally (re)index a single run's trace/artifact content.

    Called after a job trace is parsed so new runs appear in the issue index
    without a full rebuild. Returns the number of index rows written.
    """
    allowed = await allowed_prefixes(db)
    await db.execute("DELETE FROM issue_references WHERE pipeline_run_id = ?", (run_id,))

    written = 0
    for source, query in (
        (
            "trace_event",
            "SELECT pipeline_run_id, content FROM trace_events "
            "WHERE pipeline_run_id = ? AND content GLOB '*-[0-9]*'",
        ),
        (
            "job_trace",
            "SELECT pipeline_run_id, CAST(content AS TEXT) FROM job_artifacts "
            "WHERE pipeline_run_id = ? AND source = 'job_trace'",
        ),
    ):
        agg, _keys, _runs = await _index_rows(db, allowed, query, (run_id,), source)
        for (key, rid), cnt in agg.items():
            await db.execute(
                "INSERT OR REPLACE INTO issue_references "
                "(jira_key, pipeline_run_id, source, match_count) VALUES (?,?,?,?)",
                (key, rid, source, cnt),
            )
            written += 1

    await db.commit()
    return written


async def list_issues(
    db: aiosqlite.Connection,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List distinct Jira keys with aggregated run/pipeline stats."""
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))

    where = ""
    params: list = []
    search = (search or "").strip()
    if search:
        where = "WHERE ir.jira_key LIKE ? ESCAPE '\\'"
        params.append("%" + _like_escape(search) + "%")

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM issue_references ir {where} "
        f"GROUP BY ir.jira_key)",
        params,
    )
    total = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"""
        SELECT ir.jira_key AS jira_key,
               COUNT(DISTINCT ir.pipeline_run_id) AS run_count,
               COUNT(DISTINCT p.id) AS pipeline_count,
               SUM(ir.match_count) AS match_count,
               MAX(pr.started_at) AS last_seen,
               MIN(pr.started_at) AS first_seen,
               GROUP_CONCAT(DISTINCT p.slug) AS pipelines
        FROM issue_references ir
        JOIN pipeline_runs pr ON pr.id = ir.pipeline_run_id
        JOIN pipelines p ON p.id = pr.pipeline_id
        {where}
        GROUP BY ir.jira_key
        ORDER BY last_seen DESC, ir.jira_key
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    issues = []
    for r in await cursor.fetchall():
        d = dict(r)
        d["pipelines"] = sorted((d.pop("pipelines") or "").split(",")) if d.get("pipelines") else []
        issues.append(d)

    return {
        "issues": issues,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
