"""Tests for the GitLab CI collector with mocked HTTP."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.collector.gitlab import GitLabCollector, _STATUS_MAP, _compute_duration, _project_path_from_url
from backend.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_PIPELINE = {
    "slug": "gl-test-pipeline",
    "name": "GL Test Pipeline",
    "description": "A GitLab pipeline for collector tests",
    "owner": "qa",
    "repo_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer",
    "platform": "gitlab",
}

GITLAB_PIPELINE_RESPONSE = [
    {
        "id": 12345,
        "status": "success",
        "ref": "main",
        "created_at": "2026-06-01T10:00:00Z",
        "updated_at": "2026-06-01T10:30:00Z",
        "web_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer/-/pipelines/12345",
    },
    {
        "id": 12346,
        "status": "failed",
        "ref": "feature-branch",
        "created_at": "2026-06-01T11:00:00Z",
        "updated_at": "2026-06-01T11:15:00Z",
        "web_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer/-/pipelines/12346",
    },
    {
        "id": 12347,
        "status": "running",
        "ref": "main",
        "created_at": "2026-06-01T12:00:00Z",
        "updated_at": "2026-06-01T12:05:00Z",
        "web_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer/-/pipelines/12347",
    },
    {
        "id": 12348,
        "status": "canceled",
        "ref": "main",
        "created_at": "2026-06-01T13:00:00Z",
        "updated_at": "2026-06-01T13:02:00Z",
        "web_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer/-/pipelines/12348",
    },
]

GITLAB_PROJECT_RESPONSE = {
    "id": 99999,
    "name": "rfe-autofixer",
    "path_with_namespace": "redhat/rhel-ai/agentic-ci/rfe-autofixer",
}


def _make_mock_response(status_code=200, json_data=None, headers=None):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.headers = headers or {"RateLimit-Remaining": "100"}
    resp.text = ""
    return resp


async def _seed_pipeline(client, pipeline_data=None):
    """Create a pipeline via the API and return its id."""
    data = pipeline_data or SAMPLE_PIPELINE
    resp = await client.post("/api/pipelines", json=data)
    assert resp.status_code == 201
    return resp.json()["id"]


def _build_mock_client(responses: list):
    """Build a mock httpx.AsyncClient that returns responses in order.

    ``responses`` is a list of mock response objects, returned sequentially
    from ``client.get()``.
    """
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    return mock_client


# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------


def test_project_path_from_url():
    assert (
        _project_path_from_url("https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer")
        == "redhat/rhel-ai/agentic-ci/rfe-autofixer"
    )


def test_project_path_from_url_with_git_suffix():
    assert (
        _project_path_from_url("https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer.git")
        == "redhat/rhel-ai/agentic-ci/rfe-autofixer"
    )


def test_compute_duration():
    assert _compute_duration("2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z") == 1800


def test_compute_duration_none():
    assert _compute_duration(None, "2026-06-01T10:30:00Z") is None
    assert _compute_duration("2026-06-01T10:00:00Z", None) is None
    assert _compute_duration(None, None) is None


# ---------------------------------------------------------------------------
# Integration tests — collect_runs with mocked HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitlab_collect_runs(client):
    """collect_runs returns correctly mapped run dicts."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    # Build a pipeline dict as it would come from the DB
    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())

    # Mock responses: first call = project lookup, second = pipelines list
    project_resp = _make_mock_response(200, GITLAB_PROJECT_RESPONSE)
    pipelines_resp = _make_mock_response(200, GITLAB_PIPELINE_RESPONSE)
    mock_client = _build_mock_client([project_resp, pipelines_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            runs = await collector.collect_runs(db, pipeline)

    assert len(runs) == 4

    # Check first run (success)
    assert runs[0]["external_id"] == "12345"
    assert runs[0]["status"] == "success"
    assert runs[0]["ref"] == "main"
    assert runs[0]["duration_seconds"] == 1800
    assert runs[0]["started_at"] == "2026-06-01T10:00:00Z"
    assert runs[0]["finished_at"] == "2026-06-01T10:30:00Z"
    assert "12345" in runs[0]["web_url"]

    # Check second run (failed)
    assert runs[1]["external_id"] == "12346"
    assert runs[1]["status"] == "failed"
    assert runs[1]["finished_at"] == "2026-06-01T11:15:00Z"

    # Check third run (running -> running, finished_at should be None)
    assert runs[2]["external_id"] == "12347"
    assert runs[2]["status"] == "running"
    assert runs[2]["finished_at"] is None

    # Check fourth run (canceled)
    assert runs[3]["external_id"] == "12348"
    assert runs[3]["status"] == "canceled"


@pytest.mark.asyncio
async def test_gitlab_project_id_resolution(client):
    """When platform_project_id is None, the collector resolves it via API and persists it."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())
    assert pipeline["platform_project_id"] is None

    project_resp = _make_mock_response(200, GITLAB_PROJECT_RESPONSE)
    pipelines_resp = _make_mock_response(200, [])
    mock_client = _build_mock_client([project_resp, pipelines_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            await collector.collect_runs(db, pipeline)

    # Verify project ID was persisted
    cursor = await db.execute("SELECT platform_project_id FROM pipelines WHERE id = ?", (pid,))
    row = await cursor.fetchone()
    assert dict(row)["platform_project_id"] == "99999"


@pytest.mark.asyncio
async def test_gitlab_uses_existing_project_id(client):
    """When platform_project_id is already set, skip the project lookup."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    # Pre-set the project ID
    await db.execute("UPDATE pipelines SET platform_project_id = ? WHERE id = ?", ("77777", pid))
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())

    # Only one call expected: the pipelines list (no project lookup)
    pipelines_resp = _make_mock_response(200, GITLAB_PIPELINE_RESPONSE)
    mock_client = _build_mock_client([pipelines_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            runs = await collector.collect_runs(db, pipeline)

    assert len(runs) == 4
    # Verify only 1 GET call was made (pipelines list, no project lookup)
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_gitlab_empty_token_returns_empty(client, caplog):
    """If gitlab_token is empty, return empty list and log a warning."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = ""

        collector = GitLabCollector()
        with caplog.at_level(logging.WARNING):
            runs = await collector.collect_runs(db, pipeline)

    assert runs == []
    assert "GitLab token is not configured" in caplog.text


@pytest.mark.asyncio
async def test_gitlab_api_error_handled_gracefully(client, caplog):
    """API errors should be logged, not crash."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())

    # Project lookup returns 500
    error_resp = _make_mock_response(500, None)
    error_resp.text = "Internal Server Error"
    mock_client = _build_mock_client([error_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            with caplog.at_level(logging.ERROR):
                runs = await collector.collect_runs(db, pipeline)

    assert runs == []
    assert "Failed to resolve GitLab project ID" in caplog.text


@pytest.mark.asyncio
async def test_gitlab_pipelines_endpoint_error(client, caplog):
    """If the pipelines list endpoint errors, return empty and log."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    # Pre-set project ID to skip project lookup
    await db.execute("UPDATE pipelines SET platform_project_id = ? WHERE id = ?", ("77777", pid))
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())

    error_resp = _make_mock_response(403, None)
    error_resp.text = "Forbidden"
    mock_client = _build_mock_client([error_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            with caplog.at_level(logging.ERROR):
                runs = await collector.collect_runs(db, pipeline)

    assert runs == []
    assert "Failed to fetch pipelines" in caplog.text


@pytest.mark.asyncio
async def test_gitlab_http_exception_handled(client, caplog):
    """httpx.HTTPError during project resolution should be caught and logged."""
    import httpx

    pid = await _seed_pipeline(client)
    db = await get_db()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            with caplog.at_level(logging.ERROR):
                runs = await collector.collect_runs(db, pipeline)

    assert runs == []
    assert "HTTP error resolving GitLab project ID" in caplog.text


@pytest.mark.asyncio
async def test_gitlab_status_mapping():
    """Verify all expected GitLab statuses are mapped."""
    assert _STATUS_MAP["success"] == "success"
    assert _STATUS_MAP["failed"] == "failed"
    assert _STATUS_MAP["running"] == "running"
    assert _STATUS_MAP["pending"] == "running"
    assert _STATUS_MAP["created"] == "running"
    assert _STATUS_MAP["canceled"] == "canceled"
    assert _STATUS_MAP["skipped"] == "canceled"


@pytest.mark.asyncio
async def test_gitlab_malformed_pipeline_entry(client, caplog):
    """Malformed pipeline entries in the API response should be skipped with a warning."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    await db.execute("UPDATE pipelines SET platform_project_id = ? WHERE id = ?", ("77777", pid))
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())

    # One valid entry and one missing 'id' key
    malformed_response = [
        {
            "id": 99999,
            "status": "success",
            "ref": "main",
            "created_at": "2026-06-01T10:00:00Z",
            "updated_at": "2026-06-01T10:30:00Z",
            "web_url": "https://gitlab.com/test/-/pipelines/99999",
        },
        {
            # Missing "id" key
            "status": "failed",
            "ref": "main",
            "created_at": "2026-06-01T11:00:00Z",
            "updated_at": "2026-06-01T11:15:00Z",
        },
    ]

    pipelines_resp = _make_mock_response(200, malformed_response)
    mock_client = _build_mock_client([pipelines_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            with caplog.at_level(logging.WARNING):
                runs = await collector.collect_runs(db, pipeline)

    # Only the valid entry should be returned
    assert len(runs) == 1
    assert runs[0]["external_id"] == "99999"
    assert "Skipping malformed pipeline entry" in caplog.text


# ---------------------------------------------------------------------------
# Job-filter tests
# ---------------------------------------------------------------------------

GITLAB_JOBS_RESPONSE_MATCH = [
    {"id": 1, "name": "autofix-rfe", "status": "success"},
    {"id": 2, "name": "lint", "status": "success"},
]

GITLAB_JOBS_RESPONSE_NO_MATCH = [
    {"id": 3, "name": "lint", "status": "success"},
    {"id": 4, "name": "build", "status": "success"},
]

GITLAB_JOBS_RESPONSE_PATTERN = [
    {"id": 5, "name": "iterate-123", "status": "success"},
    {"id": 6, "name": "build", "status": "success"},
]


@pytest.mark.asyncio
async def test_gitlab_job_filter_exact_match(client):
    """Pipeline with jobs filter: matching job -> run is collected with job name set."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    await db.execute("UPDATE pipelines SET platform_project_id = ? WHERE id = ?", ("77777", pid))
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())
    # Add job filter fields
    pipeline["jobs"] = json.dumps(["autofix-rfe"])
    pipeline["job_patterns"] = None

    # Responses: pipelines list, then jobs for pipeline 12345
    single_pipeline = [GITLAB_PIPELINE_RESPONSE[0]]  # id=12345
    pipelines_resp = _make_mock_response(200, single_pipeline)
    jobs_resp = _make_mock_response(200, GITLAB_JOBS_RESPONSE_MATCH)
    mock_client = _build_mock_client([pipelines_resp, jobs_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            runs = await collector.collect_runs(db, pipeline)

    assert len(runs) == 1
    assert runs[0]["external_id"] == "12345"
    assert runs[0]["job"] == "autofix-rfe"


@pytest.mark.asyncio
async def test_gitlab_job_filter_pattern_match(client):
    """Pipeline with job_patterns filter: glob match -> run is collected."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    await db.execute("UPDATE pipelines SET platform_project_id = ? WHERE id = ?", ("77777", pid))
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())
    pipeline["jobs"] = None
    pipeline["job_patterns"] = json.dumps(["iterate-*"])

    single_pipeline = [GITLAB_PIPELINE_RESPONSE[0]]
    pipelines_resp = _make_mock_response(200, single_pipeline)
    jobs_resp = _make_mock_response(200, GITLAB_JOBS_RESPONSE_PATTERN)
    mock_client = _build_mock_client([pipelines_resp, jobs_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            runs = await collector.collect_runs(db, pipeline)

    assert len(runs) == 1
    assert runs[0]["job"] == "iterate-123"


@pytest.mark.asyncio
async def test_gitlab_job_filter_no_match_skips(client, caplog):
    """Pipeline with filters but no matching jobs -> run is skipped."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    await db.execute("UPDATE pipelines SET platform_project_id = ? WHERE id = ?", ("77777", pid))
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())
    pipeline["jobs"] = json.dumps(["autofix-rfe"])
    pipeline["job_patterns"] = None

    single_pipeline = [GITLAB_PIPELINE_RESPONSE[0]]
    pipelines_resp = _make_mock_response(200, single_pipeline)
    jobs_resp = _make_mock_response(200, GITLAB_JOBS_RESPONSE_NO_MATCH)
    mock_client = _build_mock_client([pipelines_resp, jobs_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            with caplog.at_level(logging.INFO):
                runs = await collector.collect_runs(db, pipeline)

    assert len(runs) == 0
    assert "Skipped 1 pipeline(s)" in caplog.text


@pytest.mark.asyncio
async def test_gitlab_no_job_filter_collects_all(client):
    """Pipeline without filters -> all runs collected (backward compat)."""
    pid = await _seed_pipeline(client)
    db = await get_db()

    await db.execute("UPDATE pipelines SET platform_project_id = ? WHERE id = ?", ("77777", pid))
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE id = ?", (pid,))
    pipeline = dict(await cursor.fetchone())
    # No jobs/job_patterns keys at all
    assert "jobs" not in pipeline or pipeline.get("jobs") is None

    pipelines_resp = _make_mock_response(200, GITLAB_PIPELINE_RESPONSE)
    mock_client = _build_mock_client([pipelines_resp])

    with patch("backend.collector.gitlab.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            collector = GitLabCollector()
            runs = await collector.collect_runs(db, pipeline)

    # All 4 pipelines collected, no jobs API calls
    assert len(runs) == 4
    assert all(r["job"] is None for r in runs)
    # Only 1 GET call (pipelines list), no jobs fetches
    assert mock_client.get.call_count == 1
