"""Parser for MLflow artifacts into mlflow_* tables."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)


def _ms_to_iso(ms: int | float | None) -> str | None:
    """Convert milliseconds-since-epoch to ISO 8601 string, or None."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (OSError, ValueError, TypeError):
        logger.warning("Could not convert timestamp %r to ISO format", ms)
        return None


_UPSERT_EXPERIMENT_SQL = """
INSERT OR IGNORE INTO mlflow_experiments (experiment_id, name, pipeline_id)
VALUES (?, ?, ?)
"""

_UPSERT_RUN_SQL = """
INSERT OR IGNORE INTO mlflow_runs
    (run_id, experiment_id, pipeline_run_id, status, start_time, end_time)
VALUES (?, ?, ?, ?, ?, ?)
"""

_DELETE_METRICS_SQL = "DELETE FROM mlflow_metrics WHERE run_id = ?"

_INSERT_METRIC_SQL = """
INSERT INTO mlflow_metrics (run_id, key, value, timestamp, step)
VALUES (?, ?, ?, ?, ?)
"""

_DELETE_PARAMS_SQL = "DELETE FROM mlflow_params WHERE run_id = ?"

_INSERT_PARAM_SQL = """
INSERT INTO mlflow_params (run_id, key, value)
VALUES (?, ?, ?)
"""


async def parse_mlflow_artifact(
    db: aiosqlite.Connection,
    pipeline_run_id: int,
    pipeline_id: int,
    data: dict,
) -> dict:
    """Parse MLflow artifact data and insert into MLflow tables.

    Returns {"experiments": N, "runs": N, "metrics": N, "params": N} counts.
    """
    counts = {"experiments": 0, "runs": 0, "metrics": 0, "params": 0}

    if not isinstance(data, dict):
        return counts

    # --- Experiment ---
    experiment = data.get("experiment")
    experiment_id = None
    if isinstance(experiment, dict):
        experiment_id = experiment.get("experiment_id")
        name = experiment.get("name", "")
        if experiment_id is not None:
            cursor = await db.execute(
                _UPSERT_EXPERIMENT_SQL, (str(experiment_id), name, pipeline_id)
            )
            if cursor.rowcount and cursor.rowcount > 0:
                counts["experiments"] += 1

    # --- Runs ---
    runs = data.get("runs")
    if not isinstance(runs, list):
        runs = []

    for run in runs:
        if not isinstance(run, dict):
            continue

        run_id = run.get("run_id")
        if run_id is None:
            logger.warning("Skipping MLflow run with missing run_id")
            continue

        run_id = str(run_id)
        run_experiment_id = str(experiment_id) if experiment_id is not None else None
        status = run.get("status")
        start_time = _ms_to_iso(run.get("start_time"))
        end_time = _ms_to_iso(run.get("end_time"))

        cursor = await db.execute(
            _UPSERT_RUN_SQL,
            (run_id, run_experiment_id, pipeline_run_id, status, start_time, end_time),
        )
        if cursor.rowcount and cursor.rowcount > 0:
            counts["runs"] += 1

        # --- Metrics (idempotent: delete then re-insert) ---
        metrics = run.get("metrics")
        if isinstance(metrics, list):
            await db.execute(_DELETE_METRICS_SQL, (run_id,))
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                key = metric.get("key")
                value = metric.get("value")
                if key is None or value is None:
                    continue
                ts = _ms_to_iso(metric.get("timestamp"))
                step = metric.get("step", 0)
                await db.execute(
                    _INSERT_METRIC_SQL, (run_id, key, float(value), ts, step)
                )
                counts["metrics"] += 1

        # --- Params (idempotent: delete then re-insert) ---
        params = run.get("params")
        if isinstance(params, list):
            await db.execute(_DELETE_PARAMS_SQL, (run_id,))
            for param in params:
                if not isinstance(param, dict):
                    continue
                key = param.get("key")
                if key is None:
                    continue
                val = param.get("value")
                await db.execute(_INSERT_PARAM_SQL, (run_id, key, val))
                counts["params"] += 1

    await db.commit()
    return counts
