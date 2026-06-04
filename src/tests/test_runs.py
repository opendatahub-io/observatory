import pytest


SAMPLE_PIPELINE = {
    "slug": "run-test-pipeline",
    "name": "Run Test Pipeline",
    "description": "Pipeline for testing runs",
    "owner": "team-qa",
    "repo_url": "https://github.com/example/repo",
    "platform": "github",
}


@pytest.fixture
async def pipeline_with_runs(client):
    """Create a pipeline and insert test runs directly into the DB."""
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    pipeline_id = resp.json()["id"]

    from backend.database import get_db

    db = await get_db()
    for i in range(5):
        await db.execute(
            "INSERT INTO pipeline_runs (pipeline_id, external_id, status, started_at, duration_seconds) VALUES (?, ?, ?, ?, ?)",
            (
                pipeline_id,
                f"run-{i}",
                "success" if i % 2 == 0 else "failed",
                f"2026-06-0{i + 1}T00:00:00",
                100 + i * 10,
            ),
        )
    await db.commit()
    return pipeline_id


@pytest.mark.asyncio
async def test_list_runs(client, pipeline_with_runs):
    resp = await client.get("/api/pipelines/run-test-pipeline/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["per_page"] == 20
    assert len(body["runs"]) == 5
    # Ordered by started_at DESC — newest first
    assert body["runs"][0]["started_at"] == "2026-06-05T00:00:00"
    assert body["runs"][-1]["started_at"] == "2026-06-01T00:00:00"


@pytest.mark.asyncio
async def test_list_runs_empty(client):
    await client.post("/api/pipelines", json={
        "slug": "empty-pipeline",
        "name": "Empty Pipeline",
        "repo_url": "https://github.com/example/empty",
        "platform": "github",
    })
    resp = await client.get("/api/pipelines/empty-pipeline/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["runs"] == []
    assert body["page"] == 1
    assert body["per_page"] == 20


@pytest.mark.asyncio
async def test_list_runs_filter_status(client, pipeline_with_runs):
    resp = await client.get("/api/pipelines/run-test-pipeline/runs?status=success")
    assert resp.status_code == 200
    body = resp.json()
    # runs 0, 2, 4 are success
    assert body["total"] == 3
    assert len(body["runs"]) == 3
    for run in body["runs"]:
        assert run["status"] == "success"


@pytest.mark.asyncio
async def test_list_runs_pipeline_not_found(client):
    resp = await client.get("/api/pipelines/nonexistent-pipeline/runs")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run(client, pipeline_with_runs):
    # First get the list to find a run id
    resp = await client.get("/api/pipelines/run-test-pipeline/runs")
    runs = resp.json()["runs"]
    run_id = runs[0]["id"]

    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == run_id
    assert body["pipeline_id"] == pipeline_with_runs
    assert body["status"] in ("success", "failed")


@pytest.mark.asyncio
async def test_get_run_not_found(client):
    resp = await client.get("/api/runs/99999")
    assert resp.status_code == 404
