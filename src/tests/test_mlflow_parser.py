"""Tests for the MLflow artifact parser."""

import pytest

from backend.database import get_db
from backend.collector.parsers.mlflow_parser import parse_mlflow_artifact


SAMPLE_PIPELINE = {
    "slug": "mlflow-test-pipeline",
    "name": "MLflow Test Pipeline",
    "description": "Pipeline for MLflow parser tests",
    "owner": "qa",
    "repo_url": "https://gitlab.example.com/org/repo",
    "platform": "gitlab",
}


async def _seed_pipeline_and_run(client):
    """Create a pipeline and a pipeline_run, return (pipeline_id, run_id)."""
    resp = await client.post("/api/pipelines", json=SAMPLE_PIPELINE)
    assert resp.status_code == 201
    pipeline_id = resp.json()["id"]

    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO pipeline_runs (pipeline_id, external_id, status) VALUES (?, ?, ?)",
        (pipeline_id, "ext-1", "success"),
    )
    await db.commit()
    return pipeline_id, cursor.lastrowid


FULL_ARTIFACT = {
    "experiment": {
        "experiment_id": "1",
        "name": "rfe-review-batch",
    },
    "runs": [
        {
            "run_id": "abc123def456",
            "status": "FINISHED",
            "start_time": 1716883200000,
            "end_time": 1716886800000,
            "metrics": [
                {"key": "total_tokens", "value": 142000, "timestamp": 1716886800000, "step": 0},
                {"key": "cost_usd", "value": 4.23, "timestamp": 1716886800000, "step": 0},
            ],
            "params": [
                {"key": "model", "value": "claude-sonnet-4-20250514"},
                {"key": "batch_size", "value": "50"},
            ],
        }
    ],
}


@pytest.mark.asyncio
async def test_full_artifact(client):
    """Parse a complete artifact with experiment, run, metrics, and params."""
    pipeline_id, run_id = await _seed_pipeline_and_run(client)
    db = await get_db()

    counts = await parse_mlflow_artifact(db, run_id, pipeline_id, FULL_ARTIFACT)

    assert counts == {"experiments": 1, "runs": 1, "metrics": 2, "params": 2}

    # Verify experiment row
    row = await db.execute_fetchall(
        "SELECT * FROM mlflow_experiments WHERE experiment_id = '1'"
    )
    assert len(row) == 1
    assert row[0]["name"] == "rfe-review-batch"
    assert row[0]["pipeline_id"] == pipeline_id

    # Verify run row
    row = await db.execute_fetchall(
        "SELECT * FROM mlflow_runs WHERE run_id = 'abc123def456'"
    )
    assert len(row) == 1
    assert row[0]["status"] == "FINISHED"
    assert row[0]["pipeline_run_id"] == run_id
    assert row[0]["experiment_id"] == "1"
    # Timestamps should be ISO format
    assert "2024-05-28" in row[0]["start_time"]

    # Verify metrics
    metrics = await db.execute_fetchall(
        "SELECT * FROM mlflow_metrics WHERE run_id = 'abc123def456' ORDER BY key"
    )
    assert len(metrics) == 2
    assert metrics[0]["key"] == "cost_usd"
    assert metrics[0]["value"] == pytest.approx(4.23)
    assert metrics[1]["key"] == "total_tokens"
    assert metrics[1]["value"] == pytest.approx(142000)

    # Verify params
    params = await db.execute_fetchall(
        "SELECT * FROM mlflow_params WHERE run_id = 'abc123def456' ORDER BY key"
    )
    assert len(params) == 2
    assert params[0]["key"] == "batch_size"
    assert params[0]["value"] == "50"
    assert params[1]["key"] == "model"
    assert params[1]["value"] == "claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_multiple_runs(client):
    """Parse an artifact with multiple runs under one experiment."""
    pipeline_id, run_id = await _seed_pipeline_and_run(client)
    db = await get_db()

    data = {
        "experiment": {"experiment_id": "2", "name": "multi-run-exp"},
        "runs": [
            {
                "run_id": "run-aaa",
                "status": "FINISHED",
                "start_time": 1716883200000,
                "end_time": 1716886800000,
                "metrics": [
                    {"key": "accuracy", "value": 0.95, "timestamp": 1716886800000, "step": 0},
                ],
                "params": [
                    {"key": "lr", "value": "0.001"},
                ],
            },
            {
                "run_id": "run-bbb",
                "status": "FAILED",
                "metrics": [
                    {"key": "accuracy", "value": 0.80, "timestamp": 1716886800000, "step": 0},
                ],
                "params": [],
            },
        ],
    }

    counts = await parse_mlflow_artifact(db, run_id, pipeline_id, data)

    assert counts["experiments"] == 1
    assert counts["runs"] == 2
    assert counts["metrics"] == 2
    assert counts["params"] == 1

    # Both runs should reference the same experiment
    runs = await db.execute_fetchall(
        "SELECT * FROM mlflow_runs WHERE experiment_id = '2' ORDER BY run_id"
    )
    assert len(runs) == 2
    assert runs[0]["run_id"] == "run-aaa"
    assert runs[1]["run_id"] == "run-bbb"
    assert runs[1]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_missing_metrics_and_params(client):
    """Runs without metrics or params sections should be handled gracefully."""
    pipeline_id, run_id = await _seed_pipeline_and_run(client)
    db = await get_db()

    data = {
        "experiment": {"experiment_id": "3", "name": "no-metrics-exp"},
        "runs": [
            {
                "run_id": "run-no-extras",
                "status": "FINISHED",
                # No 'metrics' or 'params' keys
            }
        ],
    }

    counts = await parse_mlflow_artifact(db, run_id, pipeline_id, data)

    assert counts == {"experiments": 1, "runs": 1, "metrics": 0, "params": 0}

    # Run row should still exist
    row = await db.execute_fetchall(
        "SELECT * FROM mlflow_runs WHERE run_id = 'run-no-extras'"
    )
    assert len(row) == 1
    assert row[0]["status"] == "FINISHED"


@pytest.mark.asyncio
async def test_idempotent_reparsing(client):
    """Re-parsing the same artifact should not duplicate metrics or params."""
    pipeline_id, run_id = await _seed_pipeline_and_run(client)
    db = await get_db()

    # Parse twice
    counts1 = await parse_mlflow_artifact(db, run_id, pipeline_id, FULL_ARTIFACT)
    counts2 = await parse_mlflow_artifact(db, run_id, pipeline_id, FULL_ARTIFACT)

    # Experiment and run are INSERT OR IGNORE, so second call inserts 0
    assert counts2["experiments"] == 0
    assert counts2["runs"] == 0
    # Metrics and params are delete-then-reinsert, so counts stay the same
    assert counts2["metrics"] == 2
    assert counts2["params"] == 2

    # Verify no duplicates in the database
    metrics = await db.execute_fetchall(
        "SELECT * FROM mlflow_metrics WHERE run_id = 'abc123def456'"
    )
    assert len(metrics) == 2

    params = await db.execute_fetchall(
        "SELECT * FROM mlflow_params WHERE run_id = 'abc123def456'"
    )
    assert len(params) == 2


@pytest.mark.asyncio
async def test_empty_data(client):
    """Empty or non-dict data should return zero counts."""
    pipeline_id, run_id = await _seed_pipeline_and_run(client)
    db = await get_db()

    # Empty dict
    counts = await parse_mlflow_artifact(db, run_id, pipeline_id, {})
    assert counts == {"experiments": 0, "runs": 0, "metrics": 0, "params": 0}

    # Non-dict input
    counts = await parse_mlflow_artifact(db, run_id, pipeline_id, "not a dict")
    assert counts == {"experiments": 0, "runs": 0, "metrics": 0, "params": 0}

    # None-like data
    counts = await parse_mlflow_artifact(db, run_id, pipeline_id, None)
    assert counts == {"experiments": 0, "runs": 0, "metrics": 0, "params": 0}
