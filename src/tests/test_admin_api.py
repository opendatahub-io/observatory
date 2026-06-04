"""Tests for the admin API endpoints (db-health and purge)."""

import pytest

from backend.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_pipeline_and_run(db):
    """Insert a pipeline and a pipeline_run for foreign-key references."""
    await db.execute(
        "INSERT INTO pipelines (id, slug, name, repo_url, platform) VALUES (?, ?, ?, ?, ?)",
        (1, "admin-test", "Admin Test", "https://example.com/repo", "github"),
    )
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status) VALUES (?, ?, ?, ?)",
        (1, 1, "run-admin-001", "success"),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# GET /api/admin/db-health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_health_returns_table_counts(client):
    db = await get_db()
    await _seed_pipeline_and_run(db)

    resp = await client.get("/api/admin/db-health")
    assert resp.status_code == 200
    body = resp.json()

    assert "database_size_bytes" in body
    assert isinstance(body["database_size_bytes"], int)
    assert body["database_size_bytes"] > 0

    counts = body["table_counts"]
    assert counts["pipelines"] == 1
    assert counts["pipeline_runs"] == 1
    assert counts["telemetry_spans"] == 0
    assert counts["telemetry_summaries"] == 0
    assert counts["run_commands"] == 0
    assert counts["run_packages"] == 0
    assert counts["run_containers"] == 0
    assert counts["container_sboms"] == 0
    assert counts["sbom_vulnerabilities"] == 0


@pytest.mark.asyncio
async def test_db_health_empty_database(client):
    resp = await client.get("/api/admin/db-health")
    assert resp.status_code == 200
    body = resp.json()
    counts = body["table_counts"]
    # All counts should be zero for a fresh database
    for table, count in counts.items():
        assert count == 0, f"Expected 0 for {table}, got {count}"


# ---------------------------------------------------------------------------
# POST /api/admin/purge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_returns_deletion_counts(client):
    db = await get_db()
    await _seed_pipeline_and_run(db)

    from datetime import datetime, timedelta, timezone
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()

    # Insert an old telemetry_span that should be purged
    await db.execute(
        "INSERT INTO telemetry_spans (pipeline_run_id, trace_id, span_id, created_at) VALUES (?, ?, ?, ?)",
        (1, "old-trace", "old-span", old_ts),
    )
    await db.commit()

    resp = await client.post("/api/admin/purge")
    assert resp.status_code == 200
    body = resp.json()

    assert body["telemetry_spans"] == 1
    assert body["run_commands"] == 0
    assert body["run_packages"] == 0
    assert body["run_containers"] == 0


@pytest.mark.asyncio
async def test_purge_nothing_to_delete(client):
    resp = await client.post("/api/admin/purge")
    assert resp.status_code == 200
    body = resp.json()

    assert body["telemetry_spans"] == 0
    assert body["run_commands"] == 0
    assert body["run_packages"] == 0
    assert body["run_containers"] == 0
