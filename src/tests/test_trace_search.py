"""Tests for trace/artifact content search and the get_run_trace chat tool."""

from __future__ import annotations

import json

import pytest

from backend.chat.tools import execute_tool
from backend.crud import traces as traces_crud
from backend.database import get_db


@pytest.fixture
async def db(tmp_db):
    return await get_db()


async def _seed(db):
    """Create a pipeline with two runs that reference a Jira key in trace/artifact
    content, plus a decoy run that does not."""
    cur = await db.execute(
        "INSERT INTO pipelines (slug, name, repo_url, platform) VALUES (?,?,?,?)",
        ("strat-pipeline", "Strat Pipeline", "https://gitlab.com/org/strat", "gitlab"),
    )
    pid = cur.lastrowid

    run_ids = {}
    for ext, started in (("100", "2026-07-24T19:00:00Z"), ("200", "2026-07-28T16:00:00Z"), ("300", "2026-07-20T10:00:00Z")):
        cur = await db.execute(
            "INSERT INTO pipeline_runs (pipeline_id, external_id, status, started_at, web_url) VALUES (?,?,?,?,?)",
            (pid, ext, "success", started, f"https://gitlab.com/org/strat/-/pipelines/{ext}"),
        )
        run_ids[ext] = cur.lastrowid

    # Run 100: two matching trace events. Run 200: one matching + one non-matching.
    events = [
        (run_ids["100"], "tool_call", "Bash: fetch_issue.py RHAISTRAT-2364 --markdown", 10),
        (run_ids["100"], "command", "python3 review.py RHAISTRAT-2364", 11),
        (run_ids["200"], "tool_call", "Bash: fetch_issue.py RHAISTRAT-2364 --labels", 20),
        (run_ids["200"], "command", "echo unrelated command", 21),
        (run_ids["300"], "command", "echo nothing to see", 5),
    ]
    for rid, etype, content, line in events:
        await db.execute(
            "INSERT INTO trace_events (pipeline_run_id, source, event_type, content, line_number) VALUES (?,?,?,?,?)",
            (rid, "job_trace", etype, content, line),
        )

    # Run 100 also has a raw job_trace artifact mentioning the key.
    await db.execute(
        "INSERT INTO job_artifacts (pipeline_run_id, source, file_path, mime_type, content) VALUES (?,?,?,?,?)",
        (run_ids["100"], "job_trace", "batch-jql/job-trace.log", "text/plain",
         b"...log line about RHAISTRAT-2364 processing...".decode().encode()),
    )
    await db.commit()
    return run_ids


@pytest.mark.anyio
async def test_search_finds_runs_by_jira_key(db):
    run_ids = await _seed(db)
    res = await traces_crud.search_trace_content(db, "RHAISTRAT-2364")

    found = {r["run_id"] for r in res["runs"]}
    assert found == {run_ids["100"], run_ids["200"]}  # decoy 300 excluded
    assert res["total_run_count"] == 2
    # 3 trace events + 1 artifact match.
    assert res["match_count"] == 4

    by_run = {r["run_id"]: r for r in res["runs"]}
    assert by_run[run_ids["100"]]["trace_event_matches"] == 2
    assert by_run[run_ids["100"]]["artifact_matches"] == 1
    assert by_run[run_ids["200"]]["trace_event_matches"] == 1
    # Newest run first.
    assert res["runs"][0]["run_id"] == run_ids["200"]


@pytest.mark.anyio
async def test_counts_accurate_under_sample_cap(db):
    """Per-run counts come from GROUP BY, not the capped sample set."""
    await _seed(db)
    res = await traces_crud.search_trace_content(db, "RHAISTRAT-2364", limit=1)

    # Only one run fits under the cap, but total is still reported.
    assert res["run_count"] == 1
    assert res["total_run_count"] == 2
    assert res["truncated"] is True
    # match_count is the true total regardless of the sample cap.
    assert res["match_count"] == 4


@pytest.mark.anyio
async def test_event_type_filter_skips_artifacts(db):
    await _seed(db)
    res = await traces_crud.search_trace_content(db, "RHAISTRAT-2364", event_type="tool_call")
    # Only the two tool_call events match; artifact search is skipped.
    assert res["match_count"] == 2
    assert all(m["kind"] == "trace_event" for m in res["trace_matches"])
    assert res["artifact_matches"] == []


@pytest.mark.anyio
async def test_pipeline_filter(db):
    await _seed(db)
    res = await traces_crud.search_trace_content(db, "RHAISTRAT-2364", pipeline_slug="does-not-exist")
    assert res["run_count"] == 0
    assert res["match_count"] == 0


@pytest.mark.anyio
async def test_like_wildcards_are_escaped(db):
    await _seed(db)
    # A query full of LIKE wildcards must match literally (nothing), not everything.
    res = await traces_crud.search_trace_content(db, "%_%")
    assert res["match_count"] == 0


@pytest.mark.anyio
async def test_search_job_traces_tool(db):
    await _seed(db)
    out = await execute_tool(db, "search_job_traces", {"query": "RHAISTRAT-2364"})
    d = json.loads(out)
    assert d["total_run_count"] == 2
    assert d["match_count"] == 4

    # Missing query is a clean error, not an exception.
    out = await execute_tool(db, "search_job_traces", {"query": "  "})
    assert json.loads(out)["error"]


@pytest.mark.anyio
async def test_get_run_trace_tool_truncates_content(db):
    run_ids = await _seed(db)
    # Add one oversized event to verify per-event truncation.
    big = "X" * 2000
    await db.execute(
        "INSERT INTO trace_events (pipeline_run_id, source, event_type, content, line_number) VALUES (?,?,?,?,?)",
        (run_ids["100"], "job_trace", "command", big, 99),
    )
    await db.commit()

    out = await execute_tool(db, "get_run_trace", {"run_id": run_ids["100"]})
    d = json.loads(out)
    assert d["run_id"] == run_ids["100"]
    assert "summary" in d and "events" in d
    oversized = [e for e in d["events"] if e["content"].startswith("X")]
    assert oversized and oversized[0]["content"].endswith("…[truncated]")
    assert len(oversized[0]["content"]) < 2000

    # Missing run_id is a clean error.
    out = await execute_tool(db, "get_run_trace", {})
    assert json.loads(out)["error"]
