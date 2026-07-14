"""GitLab CI pipeline collector."""

import asyncio
import logging
from datetime import datetime
from urllib.parse import quote_plus, urlparse

import httpx

import backend.config
from backend.collector.base import PlatformCollector
from backend.collector.job_filter import has_job_filters, matches_job_filter, parse_job_filters

logger = logging.getLogger(__name__)

# Map GitLab pipeline statuses to our internal statuses.
_STATUS_MAP: dict[str, str] = {
    "success": "success",
    "failed": "failed",
    "running": "running",
    "pending": "running",
    "created": "running",
    "canceled": "canceled",
    "cancelled": "canceled",
    "skipped": "canceled",
    "manual": "running",
    "waiting_for_resource": "running",
    "preparing": "running",
    "scheduled": "running",
}


def _gitlab_base_url(repo_url: str) -> str:
    """Derive the GitLab API v4 base URL from a repository URL.

    For example:
        https://gitlab.com/org/repo  -> https://gitlab.com/api/v4
        https://gitlab.cee.redhat.com/org/repo -> https://gitlab.cee.redhat.com/api/v4
    """
    parsed = urlparse(repo_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/v4"


def _project_path_from_url(repo_url: str) -> str:
    """Extract the project path from a GitLab repo URL.

    E.g. "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer"
         -> "redhat/rhel-ai/agentic-ci/rfe-autofixer"
    """
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    # Remove trailing .git if present
    if path.endswith(".git"):
        path = path[:-4]
    return path


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string to a datetime, or return None."""
    if not ts:
        return None
    try:
        # Handle trailing 'Z' and '+00:00' variants
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _compute_duration(created_at: str | None, updated_at: str | None) -> int | None:
    """Compute duration in seconds between created_at and updated_at."""
    start = _parse_iso(created_at)
    end = _parse_iso(updated_at)
    if start and end:
        delta = (end - start).total_seconds()
        return max(0, int(delta))
    return None


class GitLabCollector(PlatformCollector):
    """Collects pipeline runs from the GitLab CI API."""

    async def collect_runs(self, db, pipeline: dict) -> list[dict]:
        # Try DB credential first, then fall back to env var
        token = None
        try:
            from backend.crud.credentials import get_credential_for_pipeline
            token = await get_credential_for_pipeline(db, pipeline)
        except Exception as exc:
            logger.warning("DB credential lookup failed for pipeline %s: %s",
                           pipeline.get("slug", "?"), exc)

        if not token:
            token = backend.config.settings.gitlab_token

        if not token:
            logger.warning(
                "GitLab token is not configured (OBSERVATORY_GITLAB_TOKEN). "
                "Skipping collection for pipeline %s.",
                pipeline.get("slug", "?"),
            )
            return []

        repo_url = pipeline.get("repo_url", "")
        if not repo_url:
            logger.error("Pipeline %s has no repo_url", pipeline.get("slug", "?"))
            return []

        base_url = _gitlab_base_url(repo_url)
        headers = {"PRIVATE-TOKEN": token}

        async with httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=30.0,
            verify=backend.config.settings.ssl_verify,
        ) as client:
            # --- Resolve project ID if missing ---
            project_id = pipeline.get("platform_project_id")
            if not project_id:
                project_id = await self._resolve_project_id(client, pipeline, db)
                if not project_id:
                    return []

            # --- Parse job filters ---
            jobs_list, patterns_list = parse_job_filters(pipeline)
            filtering = has_job_filters(jobs_list, patterns_list)

            # --- Fetch recent pipelines ---
            return await self._fetch_pipelines(
                client, project_id, repo_url,
                jobs_list=jobs_list,
                patterns_list=patterns_list,
                filtering=filtering,
            )

    async def _resolve_project_id(
        self,
        client: httpx.AsyncClient,
        pipeline: dict,
        db,
    ) -> str | None:
        """Resolve and persist the GitLab numeric project ID."""
        repo_url = pipeline["repo_url"]
        project_path = _project_path_from_url(repo_url)
        encoded_path = quote_plus(project_path)

        logger.info(
            "Resolving GitLab project ID for path %r (pipeline %s)",
            project_path,
            pipeline.get("slug", "?"),
        )

        try:
            resp = await client.get(f"/projects/{encoded_path}")
            await self._check_rate_limit(resp)

            if resp.status_code != 200:
                logger.error(
                    "Failed to resolve GitLab project ID for %r: HTTP %d — %s",
                    project_path,
                    resp.status_code,
                    resp.text[:200],
                )
                return None

            data = resp.json()
            project_id = str(data["id"])

            # Persist to the pipelines table
            await db.execute(
                "UPDATE pipelines SET platform_project_id = ? WHERE id = ?",
                (project_id, pipeline["id"]),
            )
            await db.commit()

            logger.info(
                "Resolved project %r to ID %s",
                project_path,
                project_id,
            )
            return project_id

        except httpx.HTTPError as exc:
            logger.error(
                "HTTP error resolving GitLab project ID for %r: %s",
                project_path,
                exc,
            )
            return None

    async def _fetch_pipelines(
        self,
        client: httpx.AsyncClient,
        project_id: str,
        repo_url: str,
        *,
        jobs_list: list[str] | None = None,
        patterns_list: list[str] | None = None,
        filtering: bool = False,
    ) -> list[dict]:
        """Fetch recent pipelines from the GitLab API and return mapped run dicts."""
        jobs_list = jobs_list or []
        patterns_list = patterns_list or []

        max_pages = 3 if filtering else 1
        pipelines_data: list[dict] = []

        for page in range(1, max_pages + 1):
            try:
                resp = await client.get(
                    f"/projects/{project_id}/pipelines",
                    params={
                        "ref": "main",
                        "per_page": 100,
                        "page": page,
                        "order_by": "id",
                        "sort": "desc",
                    },
                )
                await self._check_rate_limit(resp)

                if resp.status_code != 200:
                    logger.error(
                        "Failed to fetch pipelines for project %s: HTTP %d — %s",
                        project_id,
                        resp.status_code,
                        resp.text[:200],
                    )
                    return []

                page_data = resp.json()
                if not isinstance(page_data, list):
                    logger.error(
                        "Unexpected response format from GitLab pipelines endpoint: %s",
                        type(page_data).__name__,
                    )
                    return []

                pipelines_data.extend(page_data)
                if len(page_data) < 100:
                    break

            except httpx.HTTPError as exc:
                logger.error(
                    "HTTP error fetching pipelines for project %s: %s",
                    project_id,
                    exc,
                )
                return []

        runs: list[dict] = []
        skipped_count = 0
        for p in pipelines_data:
            try:
                pipeline_id = p["id"]
                gitlab_status = p.get("status", "unknown")
                mapped_status = _STATUS_MAP.get(gitlab_status, "unknown")
                created_at = p.get("created_at")
                updated_at = p.get("updated_at")

                matched_job_name: str | None = None

                job_started_at: str | None = None
                job_finished_at: str | None = None

                if filtering:
                    matched_job = await self._check_pipeline_jobs(
                        client, project_id, pipeline_id,
                        jobs_list, patterns_list,
                    )
                    if matched_job is None:
                        skipped_count += 1
                        continue
                    matched_job_name = matched_job["name"]
                    job_status = matched_job["status"]
                    mapped_status = _STATUS_MAP.get(job_status, mapped_status)
                    job_started_at = matched_job.get("started_at")
                    job_finished_at = matched_job.get("finished_at")
                elif mapped_status == "running":
                    resolved = await self._resolve_pipeline_status_from_detail(
                        client, project_id, pipeline_id,
                    )
                    if resolved:
                        mapped_status = resolved

                effective_started = job_started_at or created_at
                effective_finished = job_finished_at or (
                    updated_at if mapped_status in ("success", "failed", "canceled") else None
                )

                run = {
                    "external_id": str(pipeline_id),
                    "job": matched_job_name,
                    "queued_at": created_at,
                    "started_at": effective_started,
                    "finished_at": effective_finished,
                    "duration_seconds": _compute_duration(effective_started, effective_finished),
                    "status": mapped_status,
                    "ref": p.get("ref"),
                    "web_url": p.get("web_url"),
                }
                runs.append(run)
            except (KeyError, TypeError) as exc:
                logger.warning("Skipping malformed pipeline entry: %s — %s", exc, p)

        if filtering and skipped_count:
            logger.info(
                "Skipped %d pipeline(s) for project %s due to job filter",
                skipped_count,
                project_id,
            )

        logger.info(
            "Fetched %d pipeline run(s) for project %s",
            len(runs),
            project_id,
        )
        return runs

    async def _check_pipeline_jobs(
        self,
        client: httpx.AsyncClient,
        project_id: str,
        pipeline_id: int,
        jobs_list: list[str],
        patterns_list: list[str],
    ) -> dict | None:
        """Fetch jobs for a CI pipeline and return the first matched job dict, or None.

        The returned dict has keys ``name`` and ``status`` so callers can use
        the job-level status instead of the parent pipeline status.
        """
        logger.debug(
            "Checking jobs for pipeline %s against filters: jobs=%s, patterns=%s",
            pipeline_id, jobs_list, patterns_list,
        )
        try:
            resp = await client.get(
                f"/projects/{project_id}/pipelines/{pipeline_id}/jobs",
            )
            await self._check_rate_limit(resp)

            if resp.status_code != 200:
                logger.warning(
                    "Failed to fetch jobs for pipeline %s: HTTP %d",
                    pipeline_id, resp.status_code,
                )
                return None

            jobs_data = resp.json()
            if not isinstance(jobs_data, list):
                return None

            job_names = [j.get("name", "") for j in jobs_data]
            for job in jobs_data:
                name = job.get("name", "")
                if matches_job_filter(name, jobs_list, patterns_list):
                    logger.debug(
                        "Pipeline %s matched job filter via job %r (status=%s)",
                        pipeline_id, name, job.get("status"),
                    )
                    return {
                        "name": name,
                        "status": job.get("status", "unknown"),
                        "started_at": job.get("started_at"),
                        "finished_at": job.get("finished_at"),
                    }

            logger.debug(
                "Pipeline %s: no jobs matched filters. Job names: %s",
                pipeline_id, job_names,
            )

        except httpx.HTTPError as exc:
            logger.warning(
                "HTTP error fetching jobs for pipeline %s: %s",
                pipeline_id, exc,
            )

        return None

    async def _resolve_pipeline_status_from_detail(
        self,
        client: httpx.AsyncClient,
        project_id: str,
        pipeline_id: int,
    ) -> str | None:
        """For pipelines reporting 'running', check jobs to infer real status.

        GitLab parent pipelines with child/bridge jobs can stay 'running' even
        after all jobs have completed.  We fetch the jobs list and derive the
        aggregate status from the individual job statuses.
        """
        try:
            resp = await client.get(
                f"/projects/{project_id}/pipelines/{pipeline_id}/jobs",
            )
            await self._check_rate_limit(resp)
            if resp.status_code != 200:
                return None

            jobs_data = resp.json()
            if not isinstance(jobs_data, list) or not jobs_data:
                logger.debug("Pipeline %s has no jobs — cannot resolve status", pipeline_id)
                return None

            active = {"running", "pending", "preparing", "waiting_for_resource"}
            statuses = [j.get("status", "unknown") for j in jobs_data]
            logger.debug("Pipeline %s job statuses: %s", pipeline_id, statuses)

            # Skip jobs that were never started (manual, scheduled, created, skipped)
            actionable = [s for s in statuses if s not in ("manual", "scheduled", "skipped", "created")]

            if not actionable:
                return "success"

            if any(s in active for s in actionable):
                return None

            if any(s == "failed" for s in actionable):
                return "failed"
            if any(s in ("canceled", "cancelled") for s in actionable):
                return "canceled"
            return "success"

        except httpx.HTTPError:
            return None

    async def _check_rate_limit(self, resp: httpx.Response) -> None:
        """If the GitLab rate-limit remaining is low, sleep briefly."""
        remaining = resp.headers.get("RateLimit-Remaining")
        if remaining is not None:
            try:
                remaining_int = int(remaining)
                if remaining_int < 5:
                    logger.warning(
                        "GitLab rate limit nearly exhausted (%d remaining), sleeping 10s",
                        remaining_int,
                    )
                    await asyncio.sleep(10)
            except ValueError:
                pass
