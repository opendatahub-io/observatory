import logging
from datetime import datetime
from urllib.parse import urlparse

import httpx

import backend.config
from backend.collector.base import PlatformCollector
from backend.collector.job_filter import has_job_filters, matches_job_filter, parse_job_filters

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"

# Map (status, conclusion) to our normalized status.
_STATUS_MAP = {
    ("completed", "success"): "success",
    ("completed", "failure"): "failed",
    ("completed", "cancelled"): "canceled",
    ("in_progress", None): "running",
    ("queued", None): "running",
    ("waiting", None): "running",
}


def _parse_owner_repo(repo_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub repo URL."""
    parsed = urlparse(repo_url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Cannot extract owner/repo from URL: {repo_url!r}")
    owner, repo = parts[0], parts[1]
    # Strip .git suffix if present
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _map_status(status: str, conclusion: str | None) -> str:
    """Map GitHub run status/conclusion to our normalized status string."""
    key = (status, conclusion)
    mapped = _STATUS_MAP.get(key)
    if mapped is not None:
        return mapped
    # For in_progress/queued/waiting with any conclusion, still treat as running
    if status in ("in_progress", "queued", "waiting"):
        return "running"
    # For completed with any other conclusion, use the conclusion as-is or 'unknown'
    if status == "completed":
        return conclusion or "unknown"
    return "unknown"


def _compute_duration(created_at: str, updated_at: str) -> int | None:
    """Compute duration in seconds between two ISO-8601 timestamps."""
    try:
        start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        delta = (end - start).total_seconds()
        return int(delta) if delta >= 0 else None
    except (ValueError, TypeError):
        return None


class GitHubCollector(PlatformCollector):
    """Collector that fetches workflow runs from the GitHub Actions API."""

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
            token = backend.config.settings.github_token

        if not token:
            logger.warning(
                "No GitHub token configured (OBSERVATORY_GITHUB_TOKEN). "
                "Skipping collection for pipeline %s.",
                pipeline.get("slug", "?"),
            )
            return []

        repo_url = pipeline.get("repo_url", "")
        try:
            owner, repo = _parse_owner_repo(repo_url)
        except ValueError:
            logger.error("Invalid repo_url for pipeline %s: %s", pipeline.get("slug", "?"), repo_url)
            return []

        url = f"{API_BASE}/repos/{owner}/{repo}/actions/runs?per_page=20"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }

        try:
            async with httpx.AsyncClient(verify=backend.config.settings.ssl_verify) as client:
                response = await client.get(url, headers=headers, timeout=30.0)

                # Check rate limiting
                remaining = response.headers.get("x-ratelimit-remaining")
                if remaining is not None:
                    try:
                        remaining_int = int(remaining)
                        if remaining_int <= 10:
                            logger.warning(
                                "GitHub API rate limit nearly exhausted: %d requests remaining.",
                                remaining_int,
                            )
                    except ValueError:
                        pass

                if response.status_code == 403:
                    logger.error(
                        "GitHub API returned 403 for %s/%s. Possible rate limit or permissions issue.",
                        owner, repo,
                    )
                    return []

                if response.status_code != 200:
                    logger.error(
                        "GitHub API returned status %d for %s/%s: %s",
                        response.status_code, owner, repo,
                        response.text[:500],
                    )
                    return []

                data = response.json()
        except httpx.HTTPError as exc:
            logger.error(
                "HTTP error fetching workflow runs for %s/%s: %s",
                owner, repo, exc,
            )
            return []
        except Exception as exc:
            logger.error(
                "Unexpected error fetching workflow runs for %s/%s: %s",
                owner, repo, exc,
            )
            return []

        workflow_runs = data.get("workflow_runs", [])
        results: list[dict] = []

        # --- Job filtering ---
        jobs_list, patterns_list = parse_job_filters(pipeline)
        filtering = has_job_filters(jobs_list, patterns_list)
        skipped_count = 0

        for run in workflow_runs:
            workflow_name = run.get("name", "")

            if filtering:
                if not matches_job_filter(workflow_name, jobs_list, patterns_list):
                    logger.debug(
                        "Skipping workflow run %s (%s): no job filter match",
                        run.get("id"), workflow_name,
                    )
                    skipped_count += 1
                    continue

            status = _map_status(run.get("status", ""), run.get("conclusion"))
            created_at = run.get("created_at", "")
            updated_at = run.get("updated_at", "")
            duration = _compute_duration(created_at, updated_at)

            results.append({
                "external_id": str(run["id"]),
                "job": workflow_name if filtering else run.get("name", ""),
                "started_at": created_at,
                "finished_at": updated_at,
                "duration_seconds": duration,
                "status": status,
                "ref": run.get("head_branch", ""),
                "web_url": run.get("html_url", ""),
            })

        if filtering and skipped_count:
            logger.info(
                "Skipped %d workflow run(s) for %s/%s due to job filter",
                skipped_count, owner, repo,
            )

        logger.info(
            "Collected %d workflow runs for %s/%s (pipeline %s).",
            len(results), owner, repo, pipeline.get("slug", "?"),
        )
        return results
