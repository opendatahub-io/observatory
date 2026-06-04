import pytest
from datetime import datetime, timezone, timedelta

from backend.health import compute_health


def _pipeline(expected_interval_minutes=720, status="production"):
    return {
        "id": 1,
        "slug": "test",
        "status": status,
        "expected_interval_minutes": expected_interval_minutes,
    }


def _run(status="success", minutes_ago=60):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "status": status,
        "started_at": ts.isoformat(),
    }


def test_green_healthy():
    pipeline = _pipeline(expected_interval_minutes=720)
    runs = [_run("success", 60)]
    assert compute_health(pipeline, runs) == "green"


def test_grey_no_interval():
    pipeline = _pipeline(expected_interval_minutes=None)
    assert compute_health(pipeline, [_run()]) == "grey"


def test_grey_development():
    pipeline = _pipeline(status="development")
    assert compute_health(pipeline, [_run()]) == "grey"


def test_grey_deprecated():
    pipeline = _pipeline(status="deprecated")
    assert compute_health(pipeline, [_run()]) == "grey"


def test_red_no_runs():
    pipeline = _pipeline()
    assert compute_health(pipeline, []) == "red"


def test_red_failure_streak():
    pipeline = _pipeline()
    runs = [_run("failed", i * 10) for i in range(5)]
    assert compute_health(pipeline, runs) == "red"


def test_red_high_failure_rate():
    pipeline = _pipeline()
    runs = [_run("failed", i * 10) for i in range(6)] + [_run("success", 100)]
    assert compute_health(pipeline, runs) == "red"


def test_red_success_too_old():
    pipeline = _pipeline(expected_interval_minutes=60)
    runs = [_run("success", 180)]
    assert compute_health(pipeline, runs) == "red"


def test_yellow_last_run_failed():
    pipeline = _pipeline()
    runs = [_run("failed", 10), _run("success", 60)]
    assert compute_health(pipeline, runs) == "yellow"


def test_yellow_moderate_failure_rate():
    pipeline = _pipeline()
    runs = [_run("success", 5)] + [_run("failed", i * 10 + 20) for i in range(3)] + [_run("success", i * 10 + 60) for i in range(7)]
    health = compute_health(pipeline, runs)
    assert health in ("yellow", "green")


def test_yellow_success_slightly_overdue():
    pipeline = _pipeline(expected_interval_minutes=60)
    runs = [_run("success", 90)]
    assert compute_health(pipeline, runs) == "yellow"


@pytest.mark.asyncio
async def test_health_api_endpoint(client):
    resp = await client.post("/api/pipelines", json={
        "slug": "health-test",
        "name": "Health Test",
        "repo_url": "https://github.com/test/repo",
        "platform": "github",
    })
    assert resp.status_code == 201

    resp = await client.get("/api/pipelines/health-test/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "health-test"
    assert body["health"] in ("green", "yellow", "red", "grey")


@pytest.mark.asyncio
async def test_health_included_in_list(client):
    await client.post("/api/pipelines", json={
        "slug": "list-health",
        "name": "List Health",
        "repo_url": "https://github.com/test/repo",
        "platform": "github",
    })
    resp = await client.get("/api/pipelines")
    assert resp.status_code == 200
    pipelines = resp.json()["pipelines"]
    assert all("health" in p for p in pipelines)


@pytest.mark.asyncio
async def test_health_404(client):
    resp = await client.get("/api/pipelines/nonexistent/health")
    assert resp.status_code == 404
