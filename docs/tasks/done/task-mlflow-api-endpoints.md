# Task: MLflow REST API Endpoints

## Goal

Implement the subset of the MLflow REST API that the standard `mlflow` Python client uses for experiment/run tracking.

## Acceptance Criteria

- [ ] `POST /mlflow/api/2.0/mlflow/experiments/create`
- [ ] `GET /mlflow/api/2.0/mlflow/experiments/search`
- [ ] `POST /mlflow/api/2.0/mlflow/runs/create`
- [ ] `POST /mlflow/api/2.0/mlflow/runs/update`
- [ ] `POST /mlflow/api/2.0/mlflow/runs/log-metric`
- [ ] `POST /mlflow/api/2.0/mlflow/runs/log-param`
- [ ] `GET /mlflow/api/2.0/mlflow/runs/search`
- [ ] `GET /mlflow/api/2.0/mlflow/runs/get`
- [ ] Compatible with `mlflow.set_tracking_uri()` + standard client operations
- [ ] Storage in `mlflow_experiments`, `mlflow_runs`, `mlflow_metrics`, `mlflow_params`
- [ ] Tests with actual `mlflow` Python client

## Files Likely Involved

- backend/routers/mlflow.py
- backend/schemas/mlflow.py
- backend/crud/mlflow.py
- tests/test_mlflow_api.py

## Phase

5 — MLflow Push Receiver

## Status

Pending
