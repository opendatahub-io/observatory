"""Tests for the Jira-issue index (crud.issues) and /api/issues endpoints."""

from __future__ import annotations

import pytest

from backend.crud import issues as issues_crud
from backend.database import get_db


@pytest.fixture
async def db(tmp_db):
    return await get_db()


async def _seed(db):
    """Pipeline with runs whose trace/artifact content references a mix of real
    Jira keys and noise tokens that must NOT be indexed."""
    cur = await db.execute(
        "INSERT INTO pipelines (slug, name, repo_url, platform) VALUES (?,?,?,?)",
        ("strat", "Strat", "https://gitlab.com/o/strat", "gitlab"),
    )
    pid = cur.lastrowid

    runs = {}
    for ext, started in (("100", "2026-07-20T10:00:00Z"), ("200", "2026-07-28T16:00:00Z")):
        cur = await db.execute(
            "INSERT INTO pipeline_runs (pipeline_id, external_id, status, started_at) "
            "VALUES (?,?,?,?)",
            (pid, ext, "success", started),
        )
        runs[ext] = cur.lastrowid

    events = [
        # run 100: two real-key mentions + noise that must be filtered out.
        (runs["100"], "tool_call", "fetch_issue.py RHAISTRAT-2364 --markdown"),
        (runs["100"], "command", "review RHAISTRAT-2364 again"),
        (runs["100"], "command", "FILTER-1 CRUD-2 RFE-001 are not jira keys"),
        # run 200: a different real key.
        (runs["200"], "tool_call", "fetch_issue.py RHAIRFE-100"),
    ]
    for rid, etype, content in events:
        await db.execute(
            "INSERT INTO trace_events (pipeline_run_id, source, event_type, content) "
            "VALUES (?,?,?,?)",
            (rid, "job_trace", etype, content),
        )

    # run 100 also has a raw job_trace artifact mentioning the key.
    await db.execute(
        "INSERT INTO job_artifacts (pipeline_run_id, source, file_path, mime_type, content) "
        "VALUES (?,?,?,?,?)",
        (runs["100"], "job_trace", "job-trace.log", "text/plain",
         b"log about RHAISTRAT-2364 processing"),
    )
    await db.commit()
    return runs


@pytest.mark.anyio
async def test_extract_keys_respects_allowlist():
    allowed = {"RHAISTRAT", "RHAIRFE"}
    counts = issues_crud.extract_keys(
        "RHAISTRAT-2364 twice RHAISTRAT-2364, RHAIRFE-9, FILTER-1, RFE-001", allowed
    )
    assert counts == {"RHAISTRAT-2364": 2, "RHAIRFE-9": 1}


@pytest.mark.anyio
async def test_rebuild_indexes_only_real_keys(db):
    await _seed(db)
    stats = await issues_crud.rebuild_issue_index(db)
    # Two distinct real keys; noise excluded.
    assert stats["keys"] == 2

    cursor = await db.execute("SELECT DISTINCT jira_key FROM issue_references")
    keys = {r[0] for r in await cursor.fetchall()}
    assert keys == {"RHAISTRAT-2364", "RHAIRFE-100"}


@pytest.mark.anyio
async def test_list_issues_aggregates(db):
    runs = await _seed(db)
    await issues_crud.rebuild_issue_index(db)

    res = await issues_crud.list_issues(db)
    by_key = {i["jira_key"]: i for i in res["issues"]}
    assert res["total"] == 2

    strat = by_key["RHAISTRAT-2364"]
    assert strat["run_count"] == 1
    assert strat["pipeline_count"] == 1
    assert strat["pipelines"] == ["strat"]
    # 2 trace events + 1 artifact.
    assert strat["match_count"] == 3

    # Newest run first → RHAIRFE-100 (run 200) leads.
    assert res["issues"][0]["jira_key"] == "RHAIRFE-100"
    assert runs  # sanity


@pytest.mark.anyio
async def test_list_issues_search(db):
    await _seed(db)
    await issues_crud.rebuild_issue_index(db)

    res = await issues_crud.list_issues(db, search="RHAIRFE")
    assert res["total"] == 1
    assert res["issues"][0]["jira_key"] == "RHAIRFE-100"

    # LIKE wildcards are escaped → literal, matches nothing.
    res = await issues_crud.list_issues(db, search="%_%")
    assert res["total"] == 0


@pytest.mark.anyio
async def test_index_run_is_incremental(db):
    runs = await _seed(db)
    await issues_crud.rebuild_issue_index(db)

    # Add a new event to run 200 and re-index only that run.
    await db.execute(
        "INSERT INTO trace_events (pipeline_run_id, source, event_type, content) "
        "VALUES (?,?,?,?)",
        (runs["200"], "job_trace", "command", "also mentions RHAISTRAT-2364 now"),
    )
    await db.commit()
    await issues_crud.index_run(db, runs["200"])

    cursor = await db.execute(
        "SELECT jira_key FROM issue_references WHERE pipeline_run_id = ?", (runs["200"],)
    )
    keys = {r[0] for r in await cursor.fetchall()}
    assert keys == {"RHAIRFE-100", "RHAISTRAT-2364"}

    # run 100's rows are untouched by the single-run reindex.
    cursor = await db.execute(
        "SELECT COUNT(*) FROM issue_references WHERE pipeline_run_id = ?", (runs["100"],)
    )
    assert (await cursor.fetchone())[0] > 0


@pytest.mark.anyio
async def test_allowed_prefixes_derives_from_db(db):
    # A validated claim key contributes its prefix to the allow-list.
    cur = await db.execute(
        "INSERT INTO claims (claim_text, claim_hash) VALUES (?,?)",
        ("some claim", "hash-newproj"),
    )
    claim_id = cur.lastrowid
    await db.execute(
        "INSERT INTO claim_jira_keys (claim_id, jira_key) VALUES (?,?)",
        (claim_id, "NEWPROJ-42"),
    )
    await db.commit()

    prefixes = await issues_crud.allowed_prefixes(db)
    assert "NEWPROJ" in prefixes
    assert issues_crud.DEFAULT_ALLOWED_PREFIXES <= prefixes


@pytest.mark.anyio
async def test_list_issues_chat_tool(db):
    import json

    from backend.chat.tools import execute_tool

    await _seed(db)
    await issues_crud.rebuild_issue_index(db)

    out = await execute_tool(db, "list_issues", {"search": "RHAIRFE"})
    d = json.loads(out)
    assert d["total"] == 1
    assert d["issues"][0]["jira_key"] == "RHAIRFE-100"

    # No args → lists everything.
    out = await execute_tool(db, "list_issues", {})
    assert json.loads(out)["total"] == 2


@pytest.mark.anyio
async def test_issues_endpoints(client, tmp_db):
    db = await get_db()
    await _seed(db)

    r = await client.post("/api/issues/refresh")
    assert r.status_code == 200
    assert r.json()["keys"] == 2

    r = await client.get("/api/issues", params={"search": "RHAISTRAT"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["issues"][0]["jira_key"] == "RHAISTRAT-2364"

    r = await client.get("/api/issues/RHAISTRAT-2364")
    assert r.status_code == 200
    assert r.json()["total_run_count"] == 1
