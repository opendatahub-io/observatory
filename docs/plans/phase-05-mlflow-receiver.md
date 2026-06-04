# Phase 5: MLflow Push Receiver

**Estimate:** 2-3 days
**Milestone:** M4-push-receivers

## Goal

Implement the subset of the MLflow REST API that the standard `mlflow` Python client uses. Pipelines point `mlflow.set_tracking_uri()` at Observatory and get persistent experiment/run/metric storage.

## Deliverables

- MLflow REST API subset endpoints (experiments CRUD, runs CRUD, log-metric, log-param, search)
- Storage in `mlflow_experiments`, `mlflow_runs`, `mlflow_metrics`, `mlflow_params`
- MLflow data query API for dashboard integration
- MLflow section on telemetry dashboard (experiment results, metric trends)
- Documentation for pipeline owners to switch tracking URI

## Tasks

- `task-mlflow-api-endpoints.md`
- `task-mlflow-dashboard-ui.md`

## Exit Criteria

- Standard `mlflow` Python client can create experiments, log runs, log metrics/params against Observatory
- MLflow data queryable via API and visible in dashboard
