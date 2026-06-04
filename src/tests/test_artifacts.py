"""Tests for artifact download and processing with mocked HTTP."""

import io
import logging
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.collector.artifacts import download_and_process_artifacts
from backend.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_GITLAB_PIPELINE = {
    "id": 1,
    "slug": "gl-artifact-test",
    "name": "GL Artifact Test",
    "repo_url": "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer",
    "platform": "gitlab",
    "platform_project_id": "99999",
}

SAMPLE_GITHUB_PIPELINE = {
    "id": 2,
    "slug": "gh-artifact-test",
    "name": "GH Artifact Test",
    "repo_url": "https://github.com/org/repo",
    "platform": "github",
    "platform_project_id": "12345",
}

SAMPLE_RUN = {
    "id": 10,
    "external_id": "55555",
    "pipeline_id": 1,
}


def _make_artifact_zip(*file_entries: tuple[str, str]) -> bytes:
    """Create an in-memory ZIP archive with the given (name, content) entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in file_entries:
            zf.writestr(name, content)
    buf.seek(0)
    return buf.read()


def _make_mock_response(status_code=200, json_data=None, content=None, headers=None):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.content = content or b""
    resp.headers = headers or {}
    resp.text = ""
    return resp


async def _seed_pipeline_and_run(db, pipeline_data=None, run_data=None):
    """Insert a pipeline and a run into the database, return (pipeline_dict, run_dict)."""
    p = pipeline_data or SAMPLE_GITLAB_PIPELINE
    await db.execute(
        """
        INSERT INTO pipelines (slug, name, repo_url, platform, platform_project_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (p["slug"], p["name"], p["repo_url"], p["platform"], p.get("platform_project_id")),
    )
    await db.commit()

    cursor = await db.execute("SELECT * FROM pipelines WHERE slug = ?", (p["slug"],))
    pipeline = dict(await cursor.fetchone())

    r = run_data or SAMPLE_RUN
    await db.execute(
        """
        INSERT INTO pipeline_runs (pipeline_id, external_id, status, artifacts_scraped)
        VALUES (?, ?, 'success', FALSE)
        """,
        (pipeline["id"], r["external_id"]),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT * FROM pipeline_runs WHERE pipeline_id = ? AND external_id = ?",
        (pipeline["id"], r["external_id"]),
    )
    run = dict(await cursor.fetchone())

    return pipeline, run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_zip_with_otel_summary(tmp_db, caplog):
    """A ZIP containing otel-summary.json should be detected and logged."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    # Job list response — one job with artifacts
    jobs_resp = _make_mock_response(200, json_data=[
        {"id": 100, "artifacts_file": {"filename": "artifacts.zip", "size": 1024}},
    ])

    # Artifact ZIP containing otel-summary.json
    zip_bytes = _make_artifact_zip(
        ("otel-summary.json", '{"tokens": 1000}'),
    )
    artifact_resp = _make_mock_response(200, content=zip_bytes)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[jobs_resp, artifact_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.INFO):
                await download_and_process_artifacts(db, pipeline, run)

    assert "Found otel-summary.json" in caplog.text

    # Verify artifacts_scraped was set to TRUE
    cursor = await db.execute(
        "SELECT artifacts_scraped FROM pipeline_runs WHERE id = ?",
        (run["id"],),
    )
    row = await cursor.fetchone()
    assert dict(row)["artifacts_scraped"] == 1


@pytest.mark.asyncio
async def test_artifact_zip_with_run_manifest(tmp_db, caplog):
    """A ZIP containing run-manifest.json should be detected and logged."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    jobs_resp = _make_mock_response(200, json_data=[
        {"id": 101, "artifacts_file": {"filename": "artifacts.zip", "size": 512}},
    ])

    zip_bytes = _make_artifact_zip(
        ("run-manifest.json", '{"commands": []}'),
    )
    artifact_resp = _make_mock_response(200, content=zip_bytes)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[jobs_resp, artifact_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.INFO):
                await download_and_process_artifacts(db, pipeline, run)

    assert "Found run-manifest.json" in caplog.text


@pytest.mark.asyncio
async def test_artifact_zip_with_mlflow_content(tmp_db, caplog):
    """A ZIP containing mlflow/ directory contents should be detected and logged."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    jobs_resp = _make_mock_response(200, json_data=[
        {"id": 102, "artifacts_file": {"filename": "artifacts.zip", "size": 2048}},
    ])

    zip_bytes = _make_artifact_zip(
        ("mlflow/meta.yaml", "artifact_location: ./mlartifacts"),
        ("mlflow/metrics/accuracy", "1.0 1234567890 0"),
    )
    artifact_resp = _make_mock_response(200, content=zip_bytes)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[jobs_resp, artifact_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.INFO):
                await download_and_process_artifacts(db, pipeline, run)

    assert "Found mlflow artifact" in caplog.text


@pytest.mark.asyncio
async def test_missing_artifacts_404(tmp_db, caplog):
    """A 404 from the artifacts endpoint should be handled gracefully."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    jobs_resp = _make_mock_response(200, json_data=[
        {"id": 200, "artifacts_file": {"filename": "artifacts.zip", "size": 100}},
    ])
    not_found_resp = _make_mock_response(404)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[jobs_resp, not_found_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.DEBUG):
                await download_and_process_artifacts(db, pipeline, run)

    # Should still mark as scraped
    cursor = await db.execute(
        "SELECT artifacts_scraped FROM pipeline_runs WHERE id = ?",
        (run["id"],),
    )
    row = await cursor.fetchone()
    assert dict(row)["artifacts_scraped"] == 1


@pytest.mark.asyncio
async def test_artifacts_scraped_set_true(tmp_db):
    """After processing, artifacts_scraped should be TRUE regardless of content."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    # No jobs at all — empty list
    jobs_resp = _make_mock_response(200, json_data=[])

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[jobs_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await download_and_process_artifacts(db, pipeline, run)

    cursor = await db.execute(
        "SELECT artifacts_scraped FROM pipeline_runs WHERE id = ?",
        (run["id"],),
    )
    row = await cursor.fetchone()
    assert dict(row)["artifacts_scraped"] == 1


@pytest.mark.asyncio
async def test_non_gitlab_pipeline_skipped(tmp_db, caplog):
    """Non-GitLab pipelines should be skipped entirely."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(
        db,
        pipeline_data=SAMPLE_GITHUB_PIPELINE,
        run_data={"id": 20, "external_id": "gh-run-1", "pipeline_id": 2},
    )

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with caplog.at_level(logging.DEBUG):
            await download_and_process_artifacts(db, pipeline, run)

    assert "Skipping artifact download for non-GitLab pipeline" in caplog.text

    # artifacts_scraped should remain FALSE — we didn't process it
    cursor = await db.execute(
        "SELECT artifacts_scraped FROM pipeline_runs WHERE id = ?",
        (run["id"],),
    )
    row = await cursor.fetchone()
    assert dict(row)["artifacts_scraped"] == 0


@pytest.mark.asyncio
async def test_jobs_endpoint_error(tmp_db, caplog):
    """If listing jobs fails, mark as scraped and log warning."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    error_resp = _make_mock_response(500)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[error_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.WARNING):
                await download_and_process_artifacts(db, pipeline, run)

    assert "Failed to list jobs" in caplog.text

    # Should still mark as scraped to avoid retrying forever
    cursor = await db.execute(
        "SELECT artifacts_scraped FROM pipeline_runs WHERE id = ?",
        (run["id"],),
    )
    row = await cursor.fetchone()
    assert dict(row)["artifacts_scraped"] == 1


@pytest.mark.asyncio
async def test_job_without_artifacts_skipped(tmp_db, caplog):
    """Jobs without artifacts_file should be skipped."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    # Job with no artifacts_file key
    jobs_resp = _make_mock_response(200, json_data=[
        {"id": 300, "name": "lint"},
    ])

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[jobs_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.DEBUG):
                await download_and_process_artifacts(db, pipeline, run)

    # Should mark as scraped
    cursor = await db.execute(
        "SELECT artifacts_scraped FROM pipeline_runs WHERE id = ?",
        (run["id"],),
    )
    row = await cursor.fetchone()
    assert dict(row)["artifacts_scraped"] == 1


@pytest.mark.asyncio
async def test_bad_zip_handled(tmp_db, caplog):
    """A non-ZIP artifact response should be handled without crashing."""
    db = await get_db()
    pipeline, run = await _seed_pipeline_and_run(db)

    jobs_resp = _make_mock_response(200, json_data=[
        {"id": 400, "artifacts_file": {"filename": "artifacts.zip", "size": 50}},
    ])
    bad_resp = _make_mock_response(200, content=b"this is not a zip file")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[jobs_resp, bad_resp])

    with patch("backend.collector.artifacts.backend.config") as mock_config:
        mock_config.settings.gitlab_token = "fake-token"

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with caplog.at_level(logging.WARNING):
                await download_and_process_artifacts(db, pipeline, run)

    assert "not a valid ZIP file" in caplog.text

    # Should still mark as scraped
    cursor = await db.execute(
        "SELECT artifacts_scraped FROM pipeline_runs WHERE id = ?",
        (run["id"],),
    )
    row = await cursor.fetchone()
    assert dict(row)["artifacts_scraped"] == 1
