"""Download and dispatch CI job artifacts from GitLab."""

import io
import logging
import zipfile
from urllib.parse import urlparse

import httpx

import backend.config

logger = logging.getLogger(__name__)


def _gitlab_api_base(repo_url: str) -> str:
    """Derive the GitLab API v4 base URL from a repository URL."""
    parsed = urlparse(repo_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/v4"


def _project_id_from_pipeline(pipeline: dict) -> str | None:
    """Return the numeric GitLab project ID stored on the pipeline, or None."""
    return pipeline.get("platform_project_id")


async def download_and_process_artifacts(db, pipeline: dict, run: dict) -> None:
    """Download artifacts for a pipeline run and dispatch to parsers.

    Parameters
    ----------
    db:
        An open aiosqlite database connection.
    pipeline:
        A dict representing a row from the ``pipelines`` table.  Must include
        ``platform``, ``repo_url``, and ``platform_project_id``.
    run:
        A dict representing a row from the ``pipeline_runs`` table.  Must
        include ``id``, ``external_id``, and ``pipeline_id``.
    """

    # Only process GitLab pipelines.
    if pipeline.get("platform") != "gitlab":
        logger.debug(
            "Skipping artifact download for non-GitLab pipeline %s",
            pipeline.get("slug", "?"),
        )
        return

    token = None
    try:
        from backend.crud.credentials import get_credential_for_pipeline
        token = await get_credential_for_pipeline(db, pipeline)
    except Exception as exc:
        logger.warning("DB credential lookup failed for artifact download: %s", exc)

    if not token:
        token = backend.config.settings.gitlab_token

    if not token:
        logger.warning(
            "GitLab token not configured — skipping artifact download for run %s",
            run.get("external_id"),
        )
        return

    repo_url = pipeline.get("repo_url", "")
    project_id = _project_id_from_pipeline(pipeline)
    if not repo_url or not project_id:
        logger.error(
            "Pipeline %s missing repo_url or platform_project_id — cannot download artifacts",
            pipeline.get("slug", "?"),
        )
        return

    base_url = _gitlab_api_base(repo_url)
    headers = {"PRIVATE-TOKEN": token}
    run_id = run["id"]
    pipeline_ext_id = run["external_id"]

    async with httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=60.0,
        verify=backend.config.settings.ssl_verify,
        follow_redirects=True,
    ) as client:
        # Step 1: list jobs for this pipeline run
        try:
            resp = await client.get(
                f"/projects/{project_id}/pipelines/{pipeline_ext_id}/jobs",
            )
        except httpx.HTTPError as exc:
            logger.error(
                "HTTP error listing jobs for pipeline run %s: %s",
                pipeline_ext_id,
                exc,
            )
            await _mark_artifacts_scraped(db, run_id)
            return

        if resp.status_code != 200:
            logger.warning(
                "Failed to list jobs for pipeline run %s: HTTP %d",
                pipeline_ext_id,
                resp.status_code,
            )
            await _mark_artifacts_scraped(db, run_id)
            return

        jobs = resp.json()
        if not isinstance(jobs, list):
            logger.warning(
                "Unexpected jobs response type for pipeline run %s: %s",
                pipeline_ext_id,
                type(jobs).__name__,
            )
            await _mark_artifacts_scraped(db, run_id)
            return

        # Step 2: download artifacts from each job that has them
        for job in jobs:
            job_id = job.get("id")
            # GitLab sets artifacts_file when a job has downloadable artifacts.
            if not job.get("artifacts_file") and not job.get("artifacts"):
                logger.debug(
                    "Job %s has no artifacts — skipping",
                    job_id,
                )
                continue

            await _download_job_artifacts(db, client, project_id, job_id, run_id)

    await _mark_artifacts_scraped(db, run_id)


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

_MIME_MAP = {
    ".json": "application/json",
    ".yml": "text/yaml",
    ".yaml": "text/yaml",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".py": "text/x-python",
    ".sh": "text/x-shellscript",
    ".html": "text/html",
    ".xml": "application/xml",
    ".csv": "text/csv",
}


def _guess_mime(path: str) -> str:
    for ext, mime in _MIME_MAP.items():
        if path.lower().endswith(ext):
            return mime
    return "application/octet-stream"


async def _download_job_artifacts(
    db,
    client: httpx.AsyncClient,
    project_id: str,
    job_id: int,
    run_id: int,
) -> None:
    """Download artifact ZIP for a job, extract files into job_artifacts table."""
    try:
        resp = await client.get(
            f"/projects/{project_id}/jobs/{job_id}/artifacts",
        )
    except httpx.HTTPError as exc:
        logger.error(
            "HTTP error downloading artifacts for job %s: %s",
            job_id,
            exc,
        )
        return

    if resp.status_code == 404:
        logger.debug("No artifacts found for job %s (404)", job_id)
        return

    if resp.status_code != 200:
        logger.warning(
            "Failed to download artifacts for job %s: HTTP %d",
            job_id,
            resp.status_code,
        )
        return

    try:
        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf, "r") as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            logger.debug(
                "Job %s artifact ZIP contains %d files: %s",
                job_id, len(names), names[:20],
            )

            stored = 0
            for name in names:
                info = zf.getinfo(name)
                if info.file_size > MAX_FILE_SIZE:
                    logger.debug("Skipping %s (%d bytes, exceeds limit)", name, info.file_size)
                    continue

                data = zf.read(name)
                mime = _guess_mime(name)

                await db.execute(
                    """
                    INSERT INTO job_artifacts
                        (pipeline_run_id, source, source_ref, file_path, file_size, mime_type, content)
                    VALUES (?, 'ci_job', ?, ?, ?, ?, ?)
                    """,
                    (run_id, str(job_id), name, len(data), mime, data),
                )
                stored += 1

                if name.endswith("otel-summary.json"):
                    from backend.collector.parsers.otel_summary import parse_otel_summary
                    await parse_otel_summary(db, run_id, data)

                if name.endswith("run-manifest.json"):
                    from backend.collector.parsers.manifest import parse_run_manifest
                    await parse_run_manifest(db, run_id, data)

                if "mlflow/" in name:
                    from backend.collector.parsers.mlflow_parser import parse_mlflow_artifact
                    await parse_mlflow_artifact(db, run_id, run_id, data)

            if stored:
                await db.commit()
                logger.info(
                    "Stored %d artifact files for run %s (job %s)",
                    stored, run_id, job_id,
                )

    except zipfile.BadZipFile:
        logger.warning(
            "Artifact response for job %s is not a valid ZIP file",
            job_id,
        )


async def _mark_artifacts_scraped(db, run_id: int) -> None:
    """Set artifacts_scraped = TRUE for the given run."""
    await db.execute(
        "UPDATE pipeline_runs SET artifacts_scraped = TRUE WHERE id = ?",
        (run_id,),
    )
    await db.commit()
    logger.debug("Marked run %s as artifacts_scraped", run_id)
