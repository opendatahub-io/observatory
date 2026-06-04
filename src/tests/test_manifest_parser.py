"""Tests for the run-manifest.json parser."""

import pytest

from backend.database import get_db
from backend.collector.parsers.manifest import (
    parse_run_manifest,
    extract_containers_from_ci,
)


SAMPLE_PIPELINE = {
    "slug": "manifest-test-pipeline",
    "name": "Manifest Test Pipeline",
    "description": "Pipeline for manifest parser tests",
    "owner": "qa",
    "repo_url": "https://gitlab.example.com/org/repo",
    "platform": "gitlab",
}


FULL_MANIFEST = {
    "version": "1",
    "pipeline_slug": "rfe-review",
    "commands": [
        {"step": 1, "command": "pip install -r requirements.txt", "exit_code": 0, "duration_ms": 4200},
        {"step": 2, "command": "python run_review.py --batch", "exit_code": 0, "duration_ms": 342000},
    ],
    "packages": {
        "pip": [
            {"name": "anthropic", "version": "0.52.0"},
            {"name": "opentelemetry-sdk", "version": "1.25.0"},
        ],
        "rpm": [
            {"name": "python3", "version": "3.11.9-1.el9"},
        ],
    },
    "containers": [
        {"image_ref": "quay.io/rhai/rfe-worker:v2.3.1", "image_digest": "sha256:abc123"},
    ],
}


async def _seed_pipeline_run(client) -> int:
    """Create a pipeline and a run, return the pipeline_run id."""
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    pipeline_id = resp.json()["id"]

    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO pipeline_runs (pipeline_id, external_id, status) VALUES (?, ?, ?)",
        (pipeline_id, "ext-1", "success"),
    )
    await db.commit()
    return cursor.lastrowid


@pytest.mark.asyncio
async def test_full_manifest(client):
    """Parsing a full manifest should insert commands, packages, and containers."""
    run_id = await _seed_pipeline_run(client)
    db = await get_db()

    counts = await parse_run_manifest(db, run_id, FULL_MANIFEST)

    assert counts == {"commands": 2, "packages": 3, "containers": 1}

    # Verify commands
    cursor = await db.execute(
        "SELECT step_order, command, exit_code, duration_ms, source "
        "FROM run_commands WHERE pipeline_run_id = ? ORDER BY step_order",
        (run_id,),
    )
    commands = await cursor.fetchall()
    assert len(commands) == 2
    assert commands[0]["step_order"] == 1
    assert commands[0]["command"] == "pip install -r requirements.txt"
    assert commands[0]["exit_code"] == 0
    assert commands[0]["duration_ms"] == 4200
    assert commands[0]["source"] == "manifest"
    assert commands[1]["step_order"] == 2
    assert commands[1]["command"] == "python run_review.py --batch"

    # Verify packages
    cursor = await db.execute(
        "SELECT manager, name, version, source "
        "FROM run_packages WHERE pipeline_run_id = ? ORDER BY manager, name",
        (run_id,),
    )
    packages = await cursor.fetchall()
    assert len(packages) == 3
    # pip packages (alphabetical by name)
    assert packages[0]["manager"] == "pip"
    assert packages[0]["name"] == "anthropic"
    assert packages[0]["version"] == "0.52.0"
    assert packages[0]["source"] == "manifest"
    assert packages[1]["manager"] == "pip"
    assert packages[1]["name"] == "opentelemetry-sdk"
    # rpm package
    assert packages[2]["manager"] == "rpm"
    assert packages[2]["name"] == "python3"
    assert packages[2]["version"] == "3.11.9-1.el9"

    # Verify containers
    cursor = await db.execute(
        "SELECT image_ref, image_digest, source "
        "FROM run_containers WHERE pipeline_run_id = ?",
        (run_id,),
    )
    containers = await cursor.fetchall()
    assert len(containers) == 1
    assert containers[0]["image_ref"] == "quay.io/rhai/rfe-worker:v2.3.1"
    assert containers[0]["image_digest"] == "sha256:abc123"
    assert containers[0]["source"] == "manifest"


@pytest.mark.asyncio
async def test_manifest_commands_only(client):
    """A manifest with only commands (no packages or containers) should work."""
    run_id = await _seed_pipeline_run(client)
    db = await get_db()

    manifest = {
        "version": "1",
        "commands": [
            {"step": 1, "command": "make build", "exit_code": 0, "duration_ms": 1500},
        ],
    }
    counts = await parse_run_manifest(db, run_id, manifest)

    assert counts == {"commands": 1, "packages": 0, "containers": 0}

    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM run_commands WHERE pipeline_run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 1

    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM run_packages WHERE pipeline_run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 0

    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM run_containers WHERE pipeline_run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 0


@pytest.mark.asyncio
async def test_manifest_multiple_package_managers(client):
    """Packages from multiple managers (pip + rpm) should all be inserted."""
    run_id = await _seed_pipeline_run(client)
    db = await get_db()

    manifest = {
        "version": "1",
        "packages": {
            "pip": [
                {"name": "requests", "version": "2.31.0"},
            ],
            "rpm": [
                {"name": "glibc", "version": "2.34-83.el9"},
                {"name": "openssl", "version": "3.0.7-27.el9"},
            ],
            "npm": [
                {"name": "express", "version": "4.18.2"},
            ],
        },
    }
    counts = await parse_run_manifest(db, run_id, manifest)

    assert counts["packages"] == 4
    assert counts["commands"] == 0
    assert counts["containers"] == 0

    # Check that each manager has the right count
    cursor = await db.execute(
        "SELECT manager, COUNT(*) AS cnt FROM run_packages "
        "WHERE pipeline_run_id = ? GROUP BY manager ORDER BY manager",
        (run_id,),
    )
    rows = await cursor.fetchall()
    managers = {r["manager"]: r["cnt"] for r in rows}
    assert managers == {"npm": 1, "pip": 1, "rpm": 2}


@pytest.mark.asyncio
async def test_empty_manifest(client):
    """An empty manifest should return zero counts and insert nothing."""
    run_id = await _seed_pipeline_run(client)
    db = await get_db()

    counts = await parse_run_manifest(db, run_id, {})

    assert counts == {"commands": 0, "packages": 0, "containers": 0}

    for table in ("run_commands", "run_packages", "run_containers"):
        cursor = await db.execute(
            f"SELECT COUNT(*) AS cnt FROM {table} WHERE pipeline_run_id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 0, f"Expected 0 rows in {table}"


@pytest.mark.asyncio
async def test_idempotent_reparse(client):
    """Re-parsing should delete old data and re-insert (same counts)."""
    run_id = await _seed_pipeline_run(client)
    db = await get_db()

    # First parse
    counts1 = await parse_run_manifest(db, run_id, FULL_MANIFEST)
    assert counts1 == {"commands": 2, "packages": 3, "containers": 1}

    # Second parse (idempotent)
    counts2 = await parse_run_manifest(db, run_id, FULL_MANIFEST)
    assert counts2 == {"commands": 2, "packages": 3, "containers": 1}

    # Verify no duplicate rows
    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM run_commands WHERE pipeline_run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 2

    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM run_packages WHERE pipeline_run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 3

    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM run_containers WHERE pipeline_run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_fallback_container_extraction(client):
    """extract_containers_from_ci should insert a container with source='api'."""
    run_id = await _seed_pipeline_run(client)
    db = await get_db()

    inserted = await extract_containers_from_ci(
        db, run_id, "registry.example.com/ci/runner:latest"
    )
    assert inserted == 1

    cursor = await db.execute(
        "SELECT image_ref, image_digest, source "
        "FROM run_containers WHERE pipeline_run_id = ?",
        (run_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["image_ref"] == "registry.example.com/ci/runner:latest"
    assert rows[0]["image_digest"] is None
    assert rows[0]["source"] == "api"


@pytest.mark.asyncio
async def test_fallback_container_extraction_none(client):
    """extract_containers_from_ci with None should insert nothing."""
    run_id = await _seed_pipeline_run(client)
    db = await get_db()

    inserted = await extract_containers_from_ci(db, run_id, None)
    assert inserted == 0

    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM run_containers WHERE pipeline_run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 0
