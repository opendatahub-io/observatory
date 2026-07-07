# Data Sources API

The data sources API lets you register external systems that Observatory's chat agent should know about. Registered sources appear in the agent's system prompt and are queryable via the `query_data_sources` chat tool. This is metadata registration only -- credentials are managed separately via the platform credentials API.

## Base URL

```
/api/v1/data-sources
```

## Source Types

The `source_type` field is free-text but the following conventions are used:

| Type | Typical Use |
|------|-------------|
| `mlflow` | MLflow tracking server for experiment traces, token usage, cost |
| `kubernetes` | K8s cluster for job logs, pod status |
| `jira` | Jira instance for issue linking |
| `artifact_storage` | Filesystem or object store for pipeline artifacts |
| `observatory_api` | Observatory's own API (self-reference for agents) |
| `custom` | Anything else |

## Object Schema

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "MLflow Tracking Server",
  "source_type": "mlflow",
  "endpoint": "http://mlflow.ai-pipeline.svc.cluster.local:5000",
  "description": "Stores experiment traces, token usage, and cost data for pipeline agent runs",
  "config": {
    "default_experiment": "rhoai-pipeline"
  },
  "status": "active",
  "last_health_check": null,
  "last_health_status": null,
  "created_at": "2026-06-25T12:00:00",
  "updated_at": "2026-06-25T12:00:00"
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Human-readable name |
| `source_type` | string | yes | Category (see table above) |
| `endpoint` | string | no | URL or URI for the service |
| `description` | string | no | What this source provides -- the chat agent sees this text |
| `config` | object | no | Arbitrary JSON for type-specific settings |
| `status` | string | no | `active` (default) or `inactive` |

Read-only fields: `id`, `last_health_check`, `last_health_status`, `created_at`, `updated_at`.

## Endpoints

### List data sources

```
GET /api/v1/data-sources
```

Optional query parameters:

| Parameter | Description |
|-----------|-------------|
| `status` | Filter by `active` or `inactive` |
| `source_type` | Filter by type (e.g. `mlflow`) |

**Response:** `200` with a JSON array of data source objects.

```bash
curl -s http://localhost:8000/api/v1/data-sources | python3 -m json.tool
```

```bash
# Only active MLflow sources
curl -s 'http://localhost:8000/api/v1/data-sources?status=active&source_type=mlflow'
```

### Create a data source

```
POST /api/v1/data-sources
Content-Type: application/json
```

**Response:** `201` with the created object.

```bash
curl -s -X POST http://localhost:8000/api/v1/data-sources \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "MLflow Tracking Server",
    "source_type": "mlflow",
    "endpoint": "http://mlflow.ai-pipeline.svc.cluster.local:5000",
    "description": "Stores experiment traces, token usage, and cost data for pipeline agent runs"
  }'
```

### Get a data source

```
GET /api/v1/data-sources/{source_id}
```

**Response:** `200` with the object, or `404`.

### Update a data source

```
PUT /api/v1/data-sources/{source_id}
Content-Type: application/json
```

Only include fields you want to change. Omitted fields are left unchanged.

**Response:** `200` with the updated object, or `404`.

```bash
curl -s -X PUT http://localhost:8000/api/v1/data-sources/550e8400-... \
  -H 'Content-Type: application/json' \
  -d '{"status": "inactive"}'
```

### Delete a data source

```
DELETE /api/v1/data-sources/{source_id}
```

**Response:** `204` on success, `404` if not found.

```bash
curl -s -X DELETE http://localhost:8000/api/v1/data-sources/550e8400-...
```

## Chat Agent Integration

### System prompt

Active data sources are automatically appended to the chat agent's system prompt. When a user starts a chat conversation, the agent sees something like:

```
Configured external data sources in this Observatory deployment:
- MLflow Tracking Server (mlflow): Stores experiment traces... — http://mlflow....:5000
- RHOAI Jira (jira): RHOAIENG and RHAISTRAT projects — https://issues.redhat.com

Use the query_data_sources tool for full details.
```

### query_data_sources tool

The chat agent can call the `query_data_sources` tool to get full details (including config) for all configured sources. Users can ask questions like:

- "What data sources are configured?"
- "What's the MLflow server address?"
- "Show me all Kubernetes data sources"

### query_jira tool

When a Jira data source is configured, the agent can execute JQL queries directly against the Jira REST API. It uses the endpoint URL from the active `jira` data source. Example questions:

- "How many tickets are in the RHAIRFE project?"
- "Show me the latest critical bugs in RHOAIENG"
- "What RHAISTRAT issues are in progress?"

The tool accepts a `jql` string, optional `fields`, and `max_results` (capped at 50). It returns issue keys, summaries, statuses, issue types, priorities, and creation dates.

### query_mlflow tool

When an MLflow data source is configured, the agent can query the MLflow tracking server REST API. It supports three actions:

- **search_experiments** — list experiments, optionally filtered by name
- **search_runs** — list runs across experiments, with optional filter strings
- **get_run** — get detailed metrics and params for a specific run

Example questions:

- "How many MLflow experiments are there?"
- "Show me the latest runs for the strat-tasks experiment"
- "What was the cost of run abc123?"

### query_claims with Jira key

The `query_claims` tool also accepts a `jira_key` parameter to find claims linked to a specific Jira issue:

- "Show me all claims for RHAISTRAT-320"
- "What claims were refuted for RHAIRFE-135?"

## Config Field Examples

The `config` field stores type-specific JSON. Some examples:

### MLflow

```json
{
  "default_experiment": "rhoai-pipeline",
  "tracking_uri_env": "MLFLOW_TRACKING_URI"
}
```

### Kubernetes

```json
{
  "namespace": "ai-pipeline",
  "context": "ocp-cluster",
  "job_label_selector": "app=pipeline-agent"
}
```

### Jira

```json
{
  "projects": ["RHOAIENG", "RHAIRFE", "RHAISTRAT"],
  "server_env": "JIRA_SERVER"
}
```

### Artifact Storage

```json
{
  "base_path": "/app/artifacts",
  "subdirs": ["claims", "verification", "explanations", "strace", "jobs"]
}
```

## UI

The Intelligence Settings page (`/intelligence-settings`) provides a visual interface for managing data sources. It is accessible from the sidebar under the Intelligence section.

## Seeding Data Sources

To bootstrap a deployment with standard data sources, POST them during setup:

```bash
BASE=http://localhost:8000/api/v1/data-sources

curl -s -X POST "$BASE" -H 'Content-Type: application/json' -d '{
  "name": "MLflow Tracking Server",
  "source_type": "mlflow",
  "endpoint": "http://mlflow.ai-pipeline.svc.cluster.local:5000",
  "description": "Experiment traces with token usage, cost, duration, and model metadata for pipeline agent runs"
}'

curl -s -X POST "$BASE" -H 'Content-Type: application/json' -d '{
  "name": "AI Pipeline Kubernetes",
  "source_type": "kubernetes",
  "description": "K8s cluster running pipeline agent jobs in the ai-pipeline namespace",
  "config": {"namespace": "ai-pipeline"}
}'

curl -s -X POST "$BASE" -H 'Content-Type: application/json' -d '{
  "name": "RHOAI Jira",
  "source_type": "jira",
  "endpoint": "https://issues.redhat.com",
  "description": "Issue tracker for RHOAIENG bugs, RHAIRFE feature requests, and RHAISTRAT strategies",
  "config": {"projects": ["RHOAIENG", "RHAIRFE", "RHAISTRAT"]}
}'

curl -s -X POST "$BASE" -H 'Content-Type: application/json' -d '{
  "name": "Pipeline Artifacts",
  "source_type": "artifact_storage",
  "endpoint": "/app/artifacts",
  "description": "Local filesystem storing claims, verification logs, explanations, strace output, and K8s job logs",
  "config": {"subdirs": ["claims", "verification", "explanations", "strace", "jobs", "apibodies"]}
}'
```
