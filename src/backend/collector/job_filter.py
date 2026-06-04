"""Shared job-filtering logic for CI pipeline collectors.

When a pipeline configuration specifies ``jobs`` and/or ``job_patterns``
(JSON-encoded arrays stored in the database), collectors use the helpers
in this module to decide which CI runs to keep.
"""

import fnmatch
import json


def parse_job_filters(pipeline: dict) -> tuple[list[str], list[str]]:
    """Parse jobs and job_patterns from a pipeline dict.

    Both fields arrive as JSON strings (or ``None``) from the database.
    Returns ``(jobs_list, patterns_list)`` where each is a plain Python
    list of strings (possibly empty).
    """
    jobs = json.loads(pipeline.get("jobs") or "null") or []
    patterns = json.loads(pipeline.get("job_patterns") or "null") or []
    return jobs, patterns


def has_job_filters(jobs: list[str], patterns: list[str]) -> bool:
    """Return True when at least one filter is configured."""
    return bool(jobs or patterns)


def matches_job_filter(job_name: str, jobs: list[str], patterns: list[str]) -> bool:
    """Check whether *job_name* matches any exact name or glob pattern."""
    if job_name in jobs:
        return True
    return any(fnmatch.fnmatch(job_name, p) for p in patterns)
