import pytest


SAMPLE_PIPELINE = {
    "slug": "telemetry-test",
    "name": "Telemetry Test Pipeline",
    "description": "Pipeline for testing telemetry",
    "owner": "team-qa",
    "repo_url": "https://github.com/example/repo",
    "platform": "github",
}

SAMPLE_PIPELINE_2 = {
    "slug": "telemetry-test-2",
    "name": "Telemetry Test Pipeline 2",
    "description": "Second pipeline for testing telemetry",
    "owner": "team-qa",
    "repo_url": "https://github.com/example/repo2",
    "platform": "github",
}


@pytest.fixture
async def telemetry_data(client):
    """Create pipelines, runs, and telemetry summary rows."""
    resp1 = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    pipeline_id_1 = resp1.json()["id"]

    resp2 = await client.post("/api/pipelines", json=SAMPLE_PIPELINE_2)
    pipeline_id_2 = resp2.json()["id"]

    from backend.database import get_db

    db = await get_db()

    # Insert runs for pipeline 1
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status, started_at) VALUES (?, ?, ?, ?, ?)",
        (100, pipeline_id_1, "run-1", "success", "2026-05-01T10:00:00"),
    )
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status, started_at) VALUES (?, ?, ?, ?, ?)",
        (101, pipeline_id_1, "run-2", "success", "2026-05-02T10:00:00"),
    )

    # Insert runs for pipeline 2
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status, started_at) VALUES (?, ?, ?, ?, ?)",
        (102, pipeline_id_2, "run-3", "success", "2026-05-01T12:00:00"),
    )

    # Telemetry for run-1 (pipeline 1, day 1)
    await db.execute(
        "INSERT INTO telemetry_summaries (pipeline_run_id, total_tokens, input_tokens, output_tokens, cost_usd, model, skill_name, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (100, 1000, 600, 400, 0.05, "gpt-4", "code-review", 5000),
    )
    await db.execute(
        "INSERT INTO telemetry_summaries (pipeline_run_id, total_tokens, input_tokens, output_tokens, cost_usd, model, skill_name, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (100, 500, 300, 200, 0.02, "gpt-3.5", "lint", 2000),
    )

    # Telemetry for run-2 (pipeline 1, day 2)
    await db.execute(
        "INSERT INTO telemetry_summaries (pipeline_run_id, total_tokens, input_tokens, output_tokens, cost_usd, model, skill_name, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (101, 2000, 1200, 800, 0.10, "gpt-4", "code-review", 8000),
    )

    # Telemetry for run-3 (pipeline 2, day 1)
    await db.execute(
        "INSERT INTO telemetry_summaries (pipeline_run_id, total_tokens, input_tokens, output_tokens, cost_usd, model, skill_name, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (102, 3000, 1800, 1200, 0.15, "gpt-4", "security-scan", 10000),
    )

    await db.commit()

    return {
        "pipeline_id_1": pipeline_id_1,
        "pipeline_id_2": pipeline_id_2,
    }


# -- Summary endpoint tests --


@pytest.mark.asyncio
async def test_summary_all_pipelines(client, telemetry_data):
    resp = await client.get("/api/telemetry/summary")
    assert resp.status_code == 200
    body = resp.json()
    # 1000 + 500 + 2000 + 3000 = 6500
    assert body["total_tokens"] == 6500
    # 600 + 300 + 1200 + 1800 = 3900
    assert body["input_tokens"] == 3900
    # 400 + 200 + 800 + 1200 = 2600
    assert body["output_tokens"] == 2600
    # 0.05 + 0.02 + 0.10 + 0.15 = 0.32
    assert abs(body["total_cost"] - 0.32) < 0.001
    # 3 distinct runs
    assert body["run_count"] == 3
    assert body["pipeline_slug"] is None


@pytest.mark.asyncio
async def test_summary_single_pipeline(client, telemetry_data):
    resp = await client.get("/api/telemetry/summary?pipeline=telemetry-test")
    assert resp.status_code == 200
    body = resp.json()
    # Pipeline 1: 1000 + 500 + 2000 = 3500
    assert body["total_tokens"] == 3500
    assert abs(body["total_cost"] - 0.17) < 0.001
    assert body["run_count"] == 2
    assert body["pipeline_slug"] == "telemetry-test"


@pytest.mark.asyncio
async def test_summary_with_date_filter(client, telemetry_data):
    resp = await client.get("/api/telemetry/summary?since=2026-05-02T00:00:00")
    assert resp.status_code == 200
    body = resp.json()
    # Only run-2 (started_at 2026-05-02): 2000 tokens, $0.10
    assert body["total_tokens"] == 2000
    assert abs(body["total_cost"] - 0.10) < 0.001
    assert body["run_count"] == 1


@pytest.mark.asyncio
async def test_summary_empty(client):
    """Summary with no data should return zeros."""
    resp = await client.get("/api/telemetry/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_tokens"] == 0
    assert body["input_tokens"] == 0
    assert body["output_tokens"] == 0
    assert body["total_cost"] == 0.0
    assert body["run_count"] == 0


# -- Trends endpoint tests --


@pytest.mark.asyncio
async def test_trends_all_pipelines(client, telemetry_data):
    resp = await client.get("/api/telemetry/trends")
    assert resp.status_code == 200
    body = resp.json()
    trends = body["trends"]
    # Two distinct days: 2026-05-01 and 2026-05-02
    assert len(trends) == 2
    # Day 1: run-1 (1000+500) + run-3 (3000) = 4500 tokens across 2 runs
    day1 = trends[0]
    assert day1["date"] == "2026-05-01"
    assert day1["total_tokens"] == 4500
    assert abs(day1["cost_usd"] - 0.22) < 0.001
    assert day1["run_count"] == 2
    # Day 2: run-2 (2000 tokens, 1 run)
    day2 = trends[1]
    assert day2["date"] == "2026-05-02"
    assert day2["total_tokens"] == 2000
    assert abs(day2["cost_usd"] - 0.10) < 0.001
    assert day2["run_count"] == 1


@pytest.mark.asyncio
async def test_trends_single_pipeline(client, telemetry_data):
    resp = await client.get("/api/telemetry/trends?pipeline=telemetry-test")
    assert resp.status_code == 200
    body = resp.json()
    trends = body["trends"]
    assert len(trends) == 2
    # Pipeline 1 only — Day 1: 1500 tokens, Day 2: 2000 tokens
    assert trends[0]["total_tokens"] == 1500
    assert trends[1]["total_tokens"] == 2000


@pytest.mark.asyncio
async def test_trends_empty(client):
    resp = await client.get("/api/telemetry/trends")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trends"] == []


# -- Cost breakdown endpoint tests --


@pytest.mark.asyncio
async def test_cost_breakdown(client, telemetry_data):
    resp = await client.get("/api/telemetry/cost")
    assert resp.status_code == 200
    body = resp.json()
    breakdown = body["breakdown"]
    # We have 4 distinct (pipeline, model, skill) combos:
    # telemetry-test / gpt-4 / code-review
    # telemetry-test / gpt-3.5 / lint
    # telemetry-test-2 / gpt-4 / security-scan
    assert len(breakdown) == 3
    # Ordered by total_cost DESC
    assert breakdown[0]["total_cost"] >= breakdown[1]["total_cost"]
    # Check that all expected pipelines appear
    slugs = {item["pipeline_slug"] for item in breakdown}
    assert "telemetry-test" in slugs
    assert "telemetry-test-2" in slugs


@pytest.mark.asyncio
async def test_cost_breakdown_with_dates(client, telemetry_data):
    resp = await client.get("/api/telemetry/cost?since=2026-05-02T00:00:00")
    assert resp.status_code == 200
    body = resp.json()
    breakdown = body["breakdown"]
    # Only run-2 started on May 2 — one combo: telemetry-test / gpt-4 / code-review
    assert len(breakdown) == 1
    assert breakdown[0]["pipeline_slug"] == "telemetry-test"
    assert breakdown[0]["model"] == "gpt-4"
    assert breakdown[0]["skill_name"] == "code-review"


@pytest.mark.asyncio
async def test_cost_breakdown_empty(client):
    resp = await client.get("/api/telemetry/cost")
    assert resp.status_code == 200
    body = resp.json()
    assert body["breakdown"] == []


# -- Per-pipeline telemetry endpoint tests --


@pytest.mark.asyncio
async def test_pipeline_telemetry(client, telemetry_data):
    resp = await client.get("/api/pipelines/telemetry-test/telemetry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pipeline_slug"] == "telemetry-test"
    assert body["total_tokens"] == 3500
    assert abs(body["total_cost"] - 0.17) < 0.001
    assert body["run_count"] == 2
    # 3 telemetry rows for pipeline 1
    assert len(body["rows"]) == 3
    # Rows ordered by started_at DESC — run-2 first
    assert body["rows"][0]["run_external_id"] == "run-2"


@pytest.mark.asyncio
async def test_pipeline_telemetry_with_date_filter(client, telemetry_data):
    resp = await client.get(
        "/api/pipelines/telemetry-test/telemetry?since=2026-05-02T00:00:00"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_count"] == 1
    assert len(body["rows"]) == 1
    assert body["rows"][0]["run_external_id"] == "run-2"


@pytest.mark.asyncio
async def test_pipeline_telemetry_empty(client):
    """Pipeline with no telemetry data returns zeros and empty rows."""
    await client.post(
        "/api/pipelines",
        json={
            "slug": "empty-telemetry",
            "name": "Empty Telemetry",
            "repo_url": "https://github.com/example/empty",
            "platform": "github",
        },
    )
    resp = await client.get("/api/pipelines/empty-telemetry/telemetry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pipeline_slug"] == "empty-telemetry"
    assert body["total_tokens"] == 0
    assert body["total_cost"] == 0.0
    assert body["run_count"] == 0
    assert body["rows"] == []
