import pytest

from backend.database import get_db
from backend.collector.scheduler import run_collector_cycle
from backend.collector.crud import (
    get_collector_state,
    get_collector_states,
    upsert_collector_state,
)


SAMPLE_PIPELINE = {
    "slug": "test-pipeline",
    "name": "Test Pipeline",
    "description": "A pipeline for collector tests",
    "owner": "qa",
    "repo_url": "https://gitlab.example.com/org/repo",
    "platform": "gitlab",
}


async def _seed_pipeline(client):
    """Create a pipeline via the API and return its id."""
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_run_collector_cycle_with_stubs(client):
    """run_collector_cycle should complete without error when stubs return empty lists."""
    await _seed_pipeline(client)
    db = await get_db()
    await run_collector_cycle(db)

    # After a successful cycle the collector_state row should exist
    states = await get_collector_states(db)
    assert len(states) == 1
    assert states[0]["pipeline_slug"] == "test-pipeline"
    assert states[0]["consecutive_failures"] == 0
    assert states[0]["last_error"] is None


@pytest.mark.asyncio
async def test_run_collector_cycle_empty_db(client):
    """run_collector_cycle should handle an empty pipelines table gracefully."""
    db = await get_db()
    await run_collector_cycle(db)
    # No pipelines means no collector_state rows
    states = await get_collector_states(db)
    assert states == []


@pytest.mark.asyncio
async def test_collector_status_endpoint(client):
    """GET /api/collector/status should return a list."""
    resp = await client.get("/api/collector/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_collector_status_with_pipeline(client):
    """GET /api/collector/status returns state after a cycle."""
    await _seed_pipeline(client)
    db = await get_db()
    await run_collector_cycle(db)

    resp = await client.get("/api/collector/status")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["pipeline_slug"] == "test-pipeline"


@pytest.mark.asyncio
async def test_collector_run_endpoint(client):
    """POST /api/collector/run should return 202."""
    resp = await client.post("/api/collector/run")
    assert resp.status_code == 202
    body = resp.json()
    assert "detail" in body


@pytest.mark.asyncio
async def test_upsert_collector_state_create(client):
    """upsert_collector_state should create a new row when none exists."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    await upsert_collector_state(
        db,
        pid,
        last_collected_at="2025-01-01T00:00:00Z",
        consecutive_failures=0,
    )

    state = await get_collector_state(db, pid)
    assert state is not None
    assert state["pipeline_id"] == pid
    assert state["last_collected_at"] == "2025-01-01T00:00:00Z"
    assert state["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_upsert_collector_state_update(client):
    """upsert_collector_state should update an existing row."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    # Create initial state
    await upsert_collector_state(
        db,
        pid,
        last_collected_at="2025-01-01T00:00:00Z",
        consecutive_failures=0,
    )

    # Update it
    await upsert_collector_state(
        db,
        pid,
        last_collected_at="2025-06-15T12:00:00Z",
        last_error="something went wrong",
        consecutive_failures=3,
    )

    state = await get_collector_state(db, pid)
    assert state is not None
    assert state["last_collected_at"] == "2025-06-15T12:00:00Z"
    assert state["last_error"] == "something went wrong"
    assert state["consecutive_failures"] == 3
