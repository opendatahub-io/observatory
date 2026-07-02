"""Tests for the data retention/purge job."""

import pytest
from datetime import datetime, timedelta, timezone

from backend.database import get_db
from backend.jobs.retention import purge_old_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(days_ago: int) -> str:
    """Return an ISO 8601 timestamp for ``days_ago`` days in the past."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


async def _insert_pipeline_and_run(db):
    """Insert a pipeline and pipeline_run, returning the run id."""
    await db.execute(
        "INSERT INTO pipelines (id, slug, name, repo_url, platform) VALUES (?, ?, ?, ?, ?)",
        (1, "retention-test", "Retention Test", "https://example.com/repo", "github"),
    )
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status) VALUES (?, ?, ?, ?)",
        (1, 1, "run-retention-001", "success"),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Test: Spans older than 90 days are purged, recent ones are kept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_old_telemetry_spans(client):
    db = await get_db()
    await _insert_pipeline_and_run(db)

    # Insert old span (100 days ago)
    await db.execute(
        "INSERT INTO telemetry_spans (pipeline_run_id, trace_id, span_id, created_at) VALUES (?, ?, ?, ?)",
        (1, "old-trace", "old-span", _ts(100)),
    )
    # Insert recent span (10 days ago)
    await db.execute(
        "INSERT INTO telemetry_spans (pipeline_run_id, trace_id, span_id, created_at) VALUES (?, ?, ?, ?)",
        (1, "recent-trace", "recent-span", _ts(10)),
    )
    await db.commit()

    counts = await purge_old_data(db)

    assert counts["telemetry_spans"] == 1

    cursor = await db.execute("SELECT COUNT(*) FROM telemetry_spans")
    remaining = (await cursor.fetchone())[0]
    assert remaining == 1

    cursor = await db.execute("SELECT trace_id FROM telemetry_spans")
    row = await cursor.fetchone()
    assert row["trace_id"] == "recent-trace"


# ---------------------------------------------------------------------------
# Test: Provenance data older than 180 days is purged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_old_provenance_data(client):
    db = await get_db()
    await _insert_pipeline_and_run(db)

    # Insert old run_commands (200 days ago)
    await db.execute(
        "INSERT INTO run_commands (pipeline_run_id, step_order, command, created_at) VALUES (?, ?, ?, ?)",
        (1, 1, "pip install foo", _ts(200)),
    )
    # Insert recent run_commands (30 days ago)
    await db.execute(
        "INSERT INTO run_commands (pipeline_run_id, step_order, command, created_at) VALUES (?, ?, ?, ?)",
        (1, 2, "pytest", _ts(30)),
    )

    # Insert old run_packages (200 days ago)
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version, created_at) VALUES (?, ?, ?, ?, ?)",
        (1, "pip", "old-pkg", "1.0.0", _ts(200)),
    )
    # Insert recent run_packages (30 days ago)
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version, created_at) VALUES (?, ?, ?, ?, ?)",
        (1, "pip", "new-pkg", "2.0.0", _ts(30)),
    )

    # Insert old run_containers (200 days ago)
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, created_at) VALUES (?, ?, ?)",
        (1, "old-image:v1", _ts(200)),
    )
    # Insert recent run_containers (30 days ago)
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref, created_at) VALUES (?, ?, ?)",
        (1, "new-image:v2", _ts(30)),
    )

    await db.commit()

    counts = await purge_old_data(db)

    assert counts["run_commands"] == 1
    assert counts["run_packages"] == 1
    assert counts["run_containers"] == 1

    # Verify only recent data remains
    cursor = await db.execute("SELECT COUNT(*) FROM run_commands")
    assert (await cursor.fetchone())[0] == 1

    cursor = await db.execute("SELECT COUNT(*) FROM run_packages")
    assert (await cursor.fetchone())[0] == 1

    cursor = await db.execute("SELECT COUNT(*) FROM run_containers")
    assert (await cursor.fetchone())[0] == 1


# ---------------------------------------------------------------------------
# Test: pipeline_runs and telemetry_summaries are NOT deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_does_not_delete_pipeline_runs(client):
    db = await get_db()
    await _insert_pipeline_and_run(db)

    # Insert a telemetry_summary
    await db.execute(
        "INSERT INTO telemetry_summaries (pipeline_run_id, total_tokens, source) VALUES (?, ?, ?)",
        (1, 5000, "otlp"),
    )
    await db.commit()

    counts = await purge_old_data(db)

    # pipeline_runs should still be there
    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_runs")
    assert (await cursor.fetchone())[0] == 1

    # telemetry_summaries should still be there
    cursor = await db.execute("SELECT COUNT(*) FROM telemetry_summaries")
    assert (await cursor.fetchone())[0] == 1

    # Verify the counts dict has zeros for all tables (nothing deleted)
    assert counts["telemetry_spans"] == 0
    assert counts["run_commands"] == 0
    assert counts["run_packages"] == 0
    assert counts["run_containers"] == 0


# ---------------------------------------------------------------------------
# Test: Nothing to purge returns all zeros
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_nothing_to_delete(client):
    db = await get_db()

    counts = await purge_old_data(db)

    assert counts == {
        "telemetry_spans": 0,
        "otel_log_records": 0,
        "otel_metric_points": 0,
        "run_commands": 0,
        "run_packages": 0,
        "run_containers": 0,
    }


# ---------------------------------------------------------------------------
# Test: container_sboms are NOT deleted by retention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_does_not_delete_sboms(client):
    db = await get_db()

    # Insert an SBOM
    await db.execute(
        "INSERT INTO container_sboms (image_digest, image_ref, sbom) VALUES (?, ?, ?)",
        ("sha256:retentiontest", "quay.io/test:old", '{"packages":[]}'),
    )
    await db.commit()

    await purge_old_data(db)

    cursor = await db.execute("SELECT COUNT(*) FROM container_sboms")
    assert (await cursor.fetchone())[0] == 1
