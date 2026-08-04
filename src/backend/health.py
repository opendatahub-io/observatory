"""Health status computation for pipelines.

Logic:
  green:  last successful run within 1x expected interval
          AND last run succeeded
          AND failure rate < 20% over last 10 runs
  yellow: last successful run within 2x expected interval
          OR last run failed but previous succeeded
          OR failure rate 20-50% over last 10 runs
          OR last successful run > 2x expected interval (stale)
  red:    failure streak >= 3
          OR failure rate > 50% over last 10 runs
          OR no successful run found at all
          OR no runs found in collection window
  grey:   pipeline status is 'development' or 'deprecated'
          OR fewer than 2 runs (cannot infer interval)
"""

from datetime import datetime, timezone
from statistics import median


def _infer_interval_minutes(runs: list[dict]) -> int | None:
    """Estimate the typical run interval from the median gap between runs."""
    timestamps = []
    for r in runs:
        ts = r.get("started_at")
        if ts:
            timestamps.append(_parse_ts(ts))
    if len(timestamps) < 3:
        return None
    timestamps.sort(reverse=True)
    gaps = []
    for i in range(len(timestamps) - 1):
        gap = (timestamps[i] - timestamps[i + 1]).total_seconds() / 60
        if gap > 0:
            gaps.append(gap)
    if not gaps:
        return None
    return int(median(gaps) * 1.5)


def compute_health(pipeline: dict, recent_runs: list[dict]) -> str:
    if pipeline.get("status") in ("development", "deprecated"):
        return "grey"

    expected_interval = pipeline.get("expected_interval_minutes")
    if not expected_interval:
        expected_interval = _infer_interval_minutes(recent_runs)
    if not expected_interval:
        return "grey"

    if not recent_runs:
        return "red"

    now = datetime.now(timezone.utc)

    last_run = recent_runs[0]
    last_run_status = last_run.get("status", "")

    last_success_time = None
    for run in recent_runs:
        if run.get("status") == "success":
            ts = run.get("started_at") or run.get("finished_at")
            if ts:
                last_success_time = _parse_ts(ts)
            break

    window = recent_runs[:10]
    total = len(window)
    failures = sum(1 for r in window if r.get("status") == "failed")
    failure_rate = failures / total if total > 0 else 0

    streak = 0
    for run in recent_runs:
        if run.get("status") == "failed":
            streak += 1
        else:
            break

    minutes_since_success = None
    if last_success_time:
        minutes_since_success = (now - last_success_time).total_seconds() / 60

    if streak >= 3:
        return "red"
    if failure_rate > 0.5:
        return "red"
    if minutes_since_success is None:
        return "red"

    if minutes_since_success > expected_interval * 2:
        return "yellow"
    if failure_rate >= 0.2:
        return "yellow"
    if last_run_status == "failed":
        return "yellow"
    if minutes_since_success > expected_interval:
        return "yellow"

    return "green"


def _parse_ts(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.now(timezone.utc)


async def get_pipeline_health(db, pipeline: dict) -> str:
    pipeline_id = pipeline.get("id")
    if not pipeline_id:
        return "grey"

    cursor = await db.execute(
        "SELECT external_id, status, started_at, finished_at FROM pipeline_runs "
        "WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT 10",
        (pipeline_id,),
    )
    rows = await cursor.fetchall()
    recent_runs = [dict(r) for r in rows]
    return compute_health(pipeline, recent_runs)
