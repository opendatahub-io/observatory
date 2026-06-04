import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.collector.github import GitHubCollector, _map_status, _parse_owner_repo


SAMPLE_PIPELINE = {
    "slug": "fips-compliance",
    "name": "FIPS Compliance CI",
    "repo_url": "https://github.com/red-hat-data-services/fips-compliance",
    "platform": "github",
}

SAMPLE_WORKFLOW_RUNS = {
    "total_count": 4,
    "workflow_runs": [
        {
            "id": 11111,
            "name": "CI",
            "status": "completed",
            "conclusion": "success",
            "head_branch": "main",
            "created_at": "2026-06-01T10:00:00Z",
            "updated_at": "2026-06-01T10:15:00Z",
            "html_url": "https://github.com/red-hat-data-services/fips-compliance/actions/runs/11111",
        },
        {
            "id": 22222,
            "name": "Lint",
            "status": "completed",
            "conclusion": "failure",
            "head_branch": "feature-branch",
            "created_at": "2026-06-01T11:00:00Z",
            "updated_at": "2026-06-01T11:05:00Z",
            "html_url": "https://github.com/red-hat-data-services/fips-compliance/actions/runs/22222",
        },
        {
            "id": 33333,
            "name": "Build",
            "status": "in_progress",
            "conclusion": None,
            "head_branch": "main",
            "created_at": "2026-06-01T12:00:00Z",
            "updated_at": "2026-06-01T12:02:00Z",
            "html_url": "https://github.com/red-hat-data-services/fips-compliance/actions/runs/33333",
        },
        {
            "id": 44444,
            "name": "Deploy",
            "status": "completed",
            "conclusion": "cancelled",
            "head_branch": "release",
            "created_at": "2026-06-01T09:00:00Z",
            "updated_at": "2026-06-01T09:20:00Z",
            "html_url": "https://github.com/red-hat-data-services/fips-compliance/actions/runs/44444",
        },
    ],
}


def _make_mock_response(status_code=200, json_data=None, headers=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {"x-ratelimit-remaining": "100"}
    resp.text = ""
    return resp


@pytest.mark.asyncio
async def test_collect_runs_success():
    """collect_runs should return correctly mapped run dicts."""
    mock_response = _make_mock_response(
        json_data=SAMPLE_WORKFLOW_RUNS,
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=SAMPLE_PIPELINE)

    assert len(runs) == 4

    # First run: completed + success -> success
    assert runs[0]["external_id"] == "11111"
    assert runs[0]["job"] == "CI"
    assert runs[0]["status"] == "success"
    assert runs[0]["started_at"] == "2026-06-01T10:00:00Z"
    assert runs[0]["finished_at"] == "2026-06-01T10:15:00Z"
    assert runs[0]["duration_seconds"] == 900  # 15 minutes
    assert runs[0]["ref"] == "main"
    assert "11111" in runs[0]["web_url"]

    # Second run: completed + failure -> failed
    assert runs[1]["external_id"] == "22222"
    assert runs[1]["status"] == "failed"
    assert runs[1]["duration_seconds"] == 300  # 5 minutes

    # Third run: in_progress -> running
    assert runs[2]["external_id"] == "33333"
    assert runs[2]["status"] == "running"

    # Fourth run: completed + cancelled -> canceled
    assert runs[3]["external_id"] == "44444"
    assert runs[3]["status"] == "canceled"
    assert runs[3]["duration_seconds"] == 1200  # 20 minutes


@pytest.mark.asyncio
async def test_collect_runs_empty_token(caplog):
    """collect_runs should return empty list and warn when token is empty."""
    with patch("backend.config.settings") as mock_settings:
        mock_settings.github_token = ""

        collector = GitHubCollector()
        with caplog.at_level(logging.WARNING):
            runs = await collector.collect_runs(db=None, pipeline=SAMPLE_PIPELINE)

    assert runs == []
    assert any("No GitHub token configured" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_collect_runs_api_error():
    """collect_runs should handle non-200 responses gracefully."""
    mock_response = _make_mock_response(
        status_code=500,
        headers={"x-ratelimit-remaining": "50"},
    )
    mock_response.text = "Internal Server Error"

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=SAMPLE_PIPELINE)

    assert runs == []


@pytest.mark.asyncio
async def test_collect_runs_rate_limited():
    """collect_runs should handle 403 (rate limit) gracefully."""
    mock_response = _make_mock_response(
        status_code=403,
        headers={"x-ratelimit-remaining": "0"},
    )
    mock_response.text = "API rate limit exceeded"

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=SAMPLE_PIPELINE)

    assert runs == []


@pytest.mark.asyncio
async def test_collect_runs_http_exception():
    """collect_runs should handle httpx exceptions gracefully."""
    import httpx

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=SAMPLE_PIPELINE)

    assert runs == []


@pytest.mark.asyncio
async def test_collect_runs_low_rate_limit_warning(caplog):
    """collect_runs should warn when rate limit is nearly exhausted."""
    mock_response = _make_mock_response(
        json_data={"workflow_runs": []},
        headers={"x-ratelimit-remaining": "5"},
    )

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        with caplog.at_level(logging.WARNING):
            runs = await collector.collect_runs(db=None, pipeline=SAMPLE_PIPELINE)

    assert runs == []
    assert any("rate limit nearly exhausted" in msg for msg in caplog.messages)


def test_status_mapping():
    """Test all status/conclusion combinations."""
    assert _map_status("completed", "success") == "success"
    assert _map_status("completed", "failure") == "failed"
    assert _map_status("completed", "cancelled") == "canceled"
    assert _map_status("in_progress", None) == "running"
    assert _map_status("queued", None) == "running"
    assert _map_status("waiting", None) == "running"
    # Unknown combinations
    assert _map_status("completed", "timed_out") == "timed_out"
    assert _map_status("completed", None) == "unknown"


def test_parse_owner_repo():
    """Test URL parsing for various GitHub URL formats."""
    assert _parse_owner_repo("https://github.com/owner/repo") == ("owner", "repo")
    assert _parse_owner_repo("https://github.com/owner/repo.git") == ("owner", "repo")
    assert _parse_owner_repo("https://github.com/red-hat-data-services/fips-compliance") == (
        "red-hat-data-services", "fips-compliance"
    )


def test_parse_owner_repo_invalid():
    """Test URL parsing raises ValueError for invalid URLs."""
    with pytest.raises(ValueError):
        _parse_owner_repo("https://github.com/only-owner")
    with pytest.raises(ValueError):
        _parse_owner_repo("not-a-url")


@pytest.mark.asyncio
async def test_collect_runs_invalid_repo_url():
    """collect_runs should return empty list for invalid repo_url."""
    pipeline = {**SAMPLE_PIPELINE, "repo_url": "https://github.com/bad"}

    with patch("backend.config.settings") as mock_settings:
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=pipeline)

    assert runs == []


# ---------------------------------------------------------------------------
# Job-filter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_job_filter_exact_match():
    """Workflow name matching exact job filter -> collected with job set."""
    pipeline = {
        **SAMPLE_PIPELINE,
        "jobs": json.dumps(["CI"]),
        "job_patterns": None,
    }

    mock_response = _make_mock_response(json_data=SAMPLE_WORKFLOW_RUNS)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=pipeline)

    # Only "CI" workflow should match
    assert len(runs) == 1
    assert runs[0]["external_id"] == "11111"
    assert runs[0]["job"] == "CI"


@pytest.mark.asyncio
async def test_github_job_filter_pattern_match():
    """Workflow name matching a glob pattern -> collected."""
    pipeline = {
        **SAMPLE_PIPELINE,
        "jobs": None,
        "job_patterns": json.dumps(["Build*", "Deploy*"]),
    }

    mock_response = _make_mock_response(json_data=SAMPLE_WORKFLOW_RUNS)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=pipeline)

    # "Build" and "Deploy" should match
    assert len(runs) == 2
    names = {r["job"] for r in runs}
    assert names == {"Build", "Deploy"}


@pytest.mark.asyncio
async def test_github_job_filter_no_match(caplog):
    """No workflow name matches -> all skipped."""
    pipeline = {
        **SAMPLE_PIPELINE,
        "jobs": json.dumps(["nonexistent-workflow"]),
        "job_patterns": None,
    }

    mock_response = _make_mock_response(json_data=SAMPLE_WORKFLOW_RUNS)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        with caplog.at_level(logging.INFO):
            runs = await collector.collect_runs(db=None, pipeline=pipeline)

    assert len(runs) == 0
    assert "Skipped 4 workflow run(s)" in caplog.text


@pytest.mark.asyncio
async def test_github_no_job_filter_collects_all():
    """Pipeline without filters -> all runs collected (backward compat)."""
    pipeline = {
        **SAMPLE_PIPELINE,
        # No jobs/job_patterns keys
    }

    mock_response = _make_mock_response(json_data=SAMPLE_WORKFLOW_RUNS)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.config.settings") as mock_settings, \
         patch("backend.collector.github.httpx.AsyncClient", return_value=mock_client):
        mock_settings.github_token = "ghp_test_token_123"

        collector = GitHubCollector()
        runs = await collector.collect_runs(db=None, pipeline=pipeline)

    assert len(runs) == 4
    # All workflow names should be preserved
    names = [r["job"] for r in runs]
    assert names == ["CI", "Lint", "Build", "Deploy"]
