from abc import ABC, abstractmethod
from datetime import datetime


class PlatformCollector(ABC):
    @abstractmethod
    async def collect_runs(
        self,
        db,
        pipeline: dict,
        *,
        since: datetime | None = None,
    ) -> list[dict]:
        """Fetch recent runs for a pipeline.

        Returns a list of run dicts with keys:
            external_id, job, started_at, finished_at,
            duration_seconds, status, ref, web_url.
        ``since`` is an inclusive checkpoint supplied by the scheduler.  The
        platform collector may use it to avoid fetching already completed runs.
        """
        ...


def get_collector(platform: str) -> PlatformCollector:
    """Return the appropriate collector for the given platform."""
    from backend.collector.gitlab import GitLabCollector
    from backend.collector.github import GitHubCollector

    collectors: dict[str, type[PlatformCollector]] = {
        "gitlab": GitLabCollector,
        "github": GitHubCollector,
    }
    cls = collectors.get(platform)
    if cls is None:
        raise ValueError(f"Unsupported platform: {platform!r}")
    return cls()
