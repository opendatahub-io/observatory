import logging

from backend.collector.base import PlatformCollector

logger = logging.getLogger(__name__)


class GitLabCollector(PlatformCollector):
    """Stub GitLab collector — returns no data."""

    async def collect_runs(self, db, pipeline: dict) -> list[dict]:
        logger.info(
            "GitLabCollector.collect_runs called for pipeline %s (%s) — stub, returning empty list",
            pipeline.get("slug", "?"),
            pipeline.get("repo_url", "?"),
        )
        return []


class GitHubCollector(PlatformCollector):
    """Stub GitHub collector — returns no data."""

    async def collect_runs(self, db, pipeline: dict) -> list[dict]:
        logger.info(
            "GitHubCollector.collect_runs called for pipeline %s (%s) — stub, returning empty list",
            pipeline.get("slug", "?"),
            pipeline.get("repo_url", "?"),
        )
        return []
