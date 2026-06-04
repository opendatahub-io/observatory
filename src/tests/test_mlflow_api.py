"""Tests for the MLflow REST API compatibility layer."""

import pytest


@pytest.mark.asyncio
async def test_create_experiment(client):
    resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "my-experiment"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "experiment_id" in body
    assert body["experiment_id"] == "1"


@pytest.mark.asyncio
async def test_search_experiments(client):
    # Create two experiments
    await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "exp-alpha"},
    )
    await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "exp-beta"},
    )

    resp = await client.get("/mlflow/api/2.0/mlflow/experiments/search")
    assert resp.status_code == 200
    body = resp.json()
    assert "experiments" in body
    assert len(body["experiments"]) == 2

    names = {e["name"] for e in body["experiments"]}
    assert names == {"exp-alpha", "exp-beta"}
    for exp in body["experiments"]:
        assert exp["lifecycle_stage"] == "active"


@pytest.mark.asyncio
async def test_create_run(client):
    # First create an experiment
    exp_resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "run-test-exp"},
    )
    experiment_id = exp_resp.json()["experiment_id"]

    # Create a run
    resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": experiment_id, "start_time": 1716883200000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "run" in body
    assert "info" in body["run"]
    info = body["run"]["info"]
    assert "run_id" in info
    assert len(info["run_id"]) == 32  # uuid4().hex
    assert info["experiment_id"] == experiment_id
    assert info["status"] == "RUNNING"
    assert info["start_time"] == 1716883200000


@pytest.mark.asyncio
async def test_update_run(client):
    # Setup: create experiment + run
    exp_resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "update-test"},
    )
    experiment_id = exp_resp.json()["experiment_id"]

    run_resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": experiment_id, "start_time": 1716883200000},
    )
    run_id = run_resp.json()["run"]["info"]["run_id"]

    # Update the run
    resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/update",
        json={"run_id": run_id, "status": "FINISHED", "end_time": 1716886800000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "run_info" in body
    assert body["run_info"]["run_id"] == run_id
    assert body["run_info"]["status"] == "FINISHED"
    assert body["run_info"]["end_time"] == 1716886800000


@pytest.mark.asyncio
async def test_log_metric(client):
    # Setup
    exp_resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "metric-test"},
    )
    experiment_id = exp_resp.json()["experiment_id"]

    run_resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": experiment_id},
    )
    run_id = run_resp.json()["run"]["info"]["run_id"]

    # Log a metric
    resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/log-metric",
        json={
            "run_id": run_id,
            "key": "accuracy",
            "value": 0.95,
            "timestamp": 1716886800000,
            "step": 0,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {}

    # Verify via get run
    get_resp = await client.get(
        "/mlflow/api/2.0/mlflow/runs/get", params={"run_id": run_id}
    )
    metrics = get_resp.json()["run"]["data"]["metrics"]
    assert len(metrics) == 1
    assert metrics[0]["key"] == "accuracy"
    assert metrics[0]["value"] == 0.95
    assert metrics[0]["step"] == 0


@pytest.mark.asyncio
async def test_log_param(client):
    # Setup
    exp_resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "param-test"},
    )
    experiment_id = exp_resp.json()["experiment_id"]

    run_resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": experiment_id},
    )
    run_id = run_resp.json()["run"]["info"]["run_id"]

    # Log a param
    resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/log-param",
        json={"run_id": run_id, "key": "model", "value": "claude-sonnet-4"},
    )
    assert resp.status_code == 200
    assert resp.json() == {}

    # Verify via get run
    get_resp = await client.get(
        "/mlflow/api/2.0/mlflow/runs/get", params={"run_id": run_id}
    )
    params = get_resp.json()["run"]["data"]["params"]
    assert len(params) == 1
    assert params[0]["key"] == "model"
    assert params[0]["value"] == "claude-sonnet-4"


@pytest.mark.asyncio
async def test_get_run(client):
    # Setup: create experiment, run, metrics, and params
    exp_resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "get-run-test"},
    )
    experiment_id = exp_resp.json()["experiment_id"]

    run_resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": experiment_id, "start_time": 1716883200000},
    )
    run_id = run_resp.json()["run"]["info"]["run_id"]

    # Log metric and param
    await client.post(
        "/mlflow/api/2.0/mlflow/runs/log-metric",
        json={"run_id": run_id, "key": "loss", "value": 0.05, "timestamp": 1716886800000, "step": 1},
    )
    await client.post(
        "/mlflow/api/2.0/mlflow/runs/log-param",
        json={"run_id": run_id, "key": "lr", "value": "0.001"},
    )

    # Finish the run
    await client.post(
        "/mlflow/api/2.0/mlflow/runs/update",
        json={"run_id": run_id, "status": "FINISHED", "end_time": 1716886800000},
    )

    # Get run
    resp = await client.get(
        "/mlflow/api/2.0/mlflow/runs/get", params={"run_id": run_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    run = body["run"]

    assert run["info"]["run_id"] == run_id
    assert run["info"]["experiment_id"] == experiment_id
    assert run["info"]["status"] == "FINISHED"
    assert run["info"]["start_time"] == 1716883200000
    assert run["info"]["end_time"] == 1716886800000

    assert len(run["data"]["metrics"]) == 1
    assert run["data"]["metrics"][0]["key"] == "loss"
    assert run["data"]["metrics"][0]["value"] == 0.05

    assert len(run["data"]["params"]) == 1
    assert run["data"]["params"][0]["key"] == "lr"
    assert run["data"]["params"][0]["value"] == "0.001"


@pytest.mark.asyncio
async def test_search_runs(client):
    # Create two experiments
    exp1_resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "search-exp-1"},
    )
    exp1_id = exp1_resp.json()["experiment_id"]

    exp2_resp = await client.post(
        "/mlflow/api/2.0/mlflow/experiments/create",
        json={"name": "search-exp-2"},
    )
    exp2_id = exp2_resp.json()["experiment_id"]

    # Create runs in each experiment
    run1_resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": exp1_id},
    )
    run1_id = run1_resp.json()["run"]["info"]["run_id"]

    run2_resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": exp1_id},
    )
    run2_id = run2_resp.json()["run"]["info"]["run_id"]

    await client.post(
        "/mlflow/api/2.0/mlflow/runs/create",
        json={"experiment_id": exp2_id},
    )

    # Search for runs in experiment 1 only
    resp = await client.post(
        "/mlflow/api/2.0/mlflow/runs/search",
        json={"experiment_ids": [exp1_id], "max_results": 100},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "runs" in body
    assert len(body["runs"]) == 2

    returned_ids = {r["info"]["run_id"] for r in body["runs"]}
    assert returned_ids == {run1_id, run2_id}

    # Each run should have info and data
    for run in body["runs"]:
        assert "info" in run
        assert "data" in run
        assert run["info"]["experiment_id"] == exp1_id
