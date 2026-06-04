# Agentic CI Observatory -- Operations Runbook

---

## Deployment

### Prerequisites

- OpenShift cluster with `oc` CLI authenticated
- `kustomize` (or `oc apply -k`) available
- Container registry (e.g. `quay.io`) to push the image
- GitLab and/or GitHub personal access tokens for the pipelines you want to monitor

### Build and push the container image

```bash
# From the repository root
podman build -t quay.io/observatory/observatory:latest .
podman push quay.io/observatory/observatory:latest
```

The Dockerfile is a two-stage build: Node 20 for the React frontend, Python 3.11-slim for the FastAPI backend. The final image runs as UID 1000 (non-root).

### Configure secrets

Edit `k8s/base/secret.yaml` (or use `oc create secret`) to set the real token values:

```bash
oc create secret generic observatory-secrets \
  --from-literal=OBSERVATORY_GITLAB_TOKEN='glpat-xxxx' \
  --from-literal=OBSERVATORY_GITHUB_TOKEN='ghp_xxxx' \
  --from-literal=OBSERVATORY_API_KEY='your-push-endpoint-key' \
  --dry-run=client -o yaml | oc apply -f -
```

### Deploy to OpenShift

```bash
# Base deployment (uses default namespace)
oc apply -k k8s/base

# Production overlay (sets namespace, image tag)
oc apply -k k8s/overlays/prod
```

This creates:
- **Deployment** (1 replica, 100m-500m CPU, 256Mi-512Mi memory)
- **Service** (ClusterIP on port 8000)
- **Route** (TLS edge termination)
- **PVC** (1Gi ReadWriteOnce for SQLite)
- **ConfigMap** (non-secret env vars)
- **Secret** (tokens and API key)

### Verify deployment

```bash
oc get pods -l app.kubernetes.io/name=observatory
oc logs deployment/observatory --tail=50
curl -s https://$(oc get route observatory -o jsonpath='{.spec.host}')/healthz
```

Expected: `{"status":"ok"}`

### Seed data

To load the pipeline definitions from `data/seed.json`:

```bash
oc exec deployment/observatory -- python -m backend.seed
```

Or locally during development:

```bash
python -m backend.seed
```

---

## Configuration

All environment variables use the `OBSERVATORY_` prefix (handled by pydantic-settings).

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVATORY_DATABASE_PATH` | `data/observatory.db` | Path to the SQLite database file. In the container this is `/data/observatory.db` (on the PVC). |
| `OBSERVATORY_GITLAB_TOKEN` | `""` (empty) | GitLab personal access token for the collector. Needs `read_api` scope. |
| `OBSERVATORY_GITHUB_TOKEN` | `""` (empty) | GitHub personal access token for the collector. Needs `repo` scope for private repos, `public_repo` for public. |
| `OBSERVATORY_API_KEY` | `""` (empty) | Shared secret for push endpoints (OTLP, MLflow, SBOM). If empty, authentication is disabled. |
| `OBSERVATORY_COLLECTOR_INTERVAL_MINUTES` | `30` | How often the background collector scrapes all pipelines (in minutes). |
| `OBSERVATORY_STATIC_DIR` | `frontend/dist` | Path to the built React frontend assets. |
| `OBSERVATORY_HOST` | `0.0.0.0` | Uvicorn bind address. |
| `OBSERVATORY_PORT` | `8000` | Uvicorn bind port. |

### Push endpoint authentication

The following endpoints require the `X-API-Key` header when `OBSERVATORY_API_KEY` is set:

- `POST /v1/traces` (OTLP span push)
- `POST /api/sboms` (SBOM push)
- `POST /mlflow/api/2.0/mlflow/experiments/create`
- `POST /mlflow/api/2.0/mlflow/runs/create`
- `POST /mlflow/api/2.0/mlflow/runs/update`
- `POST /mlflow/api/2.0/mlflow/runs/log-metric`
- `POST /mlflow/api/2.0/mlflow/runs/log-param`

Read endpoints (GET) are not authenticated.

---

## Backup

SQLite lives on a single file on the PVC at `OBSERVATORY_DATABASE_PATH` (default `/data/observatory.db`).

### Copy from the running pod

```bash
POD=$(oc get pod -l app.kubernetes.io/name=observatory -o jsonpath='{.items[0].metadata.name}')
oc cp "$POD:/data/observatory.db" ./observatory-backup-$(date +%Y%m%d).db
```

### Verify the backup

```bash
sqlite3 observatory-backup-*.db "SELECT count(*) FROM pipelines;"
```

### Automate with a CronJob

Create an OpenShift CronJob that runs `oc cp` on a schedule, or mount the same PVC to a sidecar that copies to object storage.

---

## Restore

### From a backup file

```bash
POD=$(oc get pod -l app.kubernetes.io/name=observatory -o jsonpath='{.items[0].metadata.name}')

# Stop the app to avoid writes during restore
oc scale deployment/observatory --replicas=0

# Copy the backup into the PVC (requires a temporary pod or the PVC mounted elsewhere)
oc cp ./observatory-backup-20260601.db "$POD:/data/observatory.db"

# Restart
oc scale deployment/observatory --replicas=1
```

Alternatively, if you can attach to the PVC directly:

```bash
# Create a debug pod with the PVC mounted
oc run restore-helper --image=python:3.11-slim --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"restore-helper","image":"python:3.11-slim","command":["sleep","3600"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"observatory-data"}}]}}'

oc cp ./observatory-backup-20260601.db restore-helper:/data/observatory.db
oc delete pod restore-helper
```

---

## Troubleshooting

### Collector failures

**Symptom**: Collector state shows `consecutive_failures > 0` or `last_error` is non-empty.

Check:
1. **Token validity** -- GitLab/GitHub tokens expire or get revoked. Rotate the secret and restart.
2. **Network connectivity** -- the pod needs outbound HTTPS to `gitlab.com` and `api.github.com`.
3. **Rate limiting** -- GitHub has a 5,000 req/hr limit; GitLab varies. Check the error message for 429 status codes.
4. **Platform project ID** -- if the pipeline's `platform_project_id` is wrong, the API returns 404.

```bash
# Check collector logs
oc logs deployment/observatory --tail=100 | grep -i collector

# Trigger a manual cycle and watch
oc logs -f deployment/observatory &
curl -X POST https://$OBSERVATORY_URL/api/collector/run
```

### Push endpoint returns 401

**Symptom**: OTLP/MLflow/SBOM push returns `{"detail":"Invalid API key"}`.

- Verify `OBSERVATORY_API_KEY` is set in the secret and the pod has restarted since the secret was updated.
- Verify the client is sending `X-API-Key: <the same value>` in the request header.
- If you want to disable auth temporarily, set `OBSERVATORY_API_KEY` to empty string.

### Database locked (SQLite)

**Symptom**: `database is locked` errors in logs.

SQLite is single-writer. This should not happen with a single replica. If it does:
1. Check that only one pod is running: `oc get pods -l app.kubernetes.io/name=observatory`
2. Check for stuck background tasks: restart the pod.
3. Consider increasing the SQLite busy timeout (not currently exposed as a config var; edit `backend/database.py` if needed).

**Never run more than 1 replica.** SQLite does not support concurrent writers across processes.

### Disk space on PVC

**Symptom**: Write errors or application crashes.

```bash
# Check PVC usage
oc exec deployment/observatory -- df -h /data

# Check database size
oc exec deployment/observatory -- ls -lh /data/observatory.db
```

If the PVC is full:
1. Expand the PVC (if the storage class supports it): `oc patch pvc observatory-data -p '{"spec":{"resources":{"requests":{"storage":"5Gi"}}}}'`
2. Purge old data (see Data Retention below).
3. Vacuum the database: `oc exec deployment/observatory -- sqlite3 /data/observatory.db VACUUM`

### Application won't start

Check:
1. Pod events: `oc describe pod -l app.kubernetes.io/name=observatory`
2. Logs: `oc logs deployment/observatory`
3. Health check: the liveness probe hits `/healthz` -- if it fails 3 times in a row, the pod restarts.

---

## Monitoring

Observatory exposes Prometheus metrics at `GET /metrics`.

### Key metrics to alert on

| Metric | Type | Alert condition | Meaning |
|--------|------|-----------------|---------|
| `pipeline_failure_streak{pipeline}` | Gauge | `> 2` | 3+ consecutive failures; pipeline is broken |
| `collector_scrape_errors_total{pipeline}` | Counter | rate > 0 for 1h | Collector cannot reach the CI platform |
| `pipeline_runs_total{pipeline,status="failed"}` | Counter | rate increasing | Pipeline failures are accelerating |
| `sbom_vulnerabilities_total{severity="Critical"}` | Gauge | `> 0` | Critical vulnerabilities exist in tracked images |
| `collector_last_scrape_timestamp{pipeline}` | Gauge | `< now() - 2 * interval` | Collector is stale; not scraping |

### Standard FastAPI metrics

The `prometheus-fastapi-instrumentator` automatically exposes:
- `http_requests_total{method,status,handler}`
- `http_request_duration_seconds{method,handler}`
- `http_request_size_bytes` / `http_response_size_bytes`

### Prometheus scrape config

```yaml
- job_name: observatory
  scrape_interval: 30s
  metrics_path: /metrics
  static_configs:
    - targets: ['observatory.observatory-prod.svc:8000']
```

Or use a `ServiceMonitor` if you have the Prometheus Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: observatory
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: observatory
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

---

## Data Retention

### What data grows

- `pipeline_runs` -- one row per CI run per pipeline per collection cycle
- `telemetry_spans` -- one row per OTLP span pushed
- `telemetry_summaries` -- one row per telemetry extraction (from artifacts or OTLP)
- `mlflow_metrics` / `mlflow_params` -- one row per logged metric/param
- `container_sboms` -- one row per unique image digest (large JSON in `sbom` column)
- `sbom_vulnerabilities` -- one row per vulnerability per SBOM

### Manual purge

```bash
# Delete pipeline runs older than 90 days
oc exec deployment/observatory -- sqlite3 /data/observatory.db \
  "DELETE FROM pipeline_runs WHERE started_at < datetime('now', '-90 days');"

# Delete orphaned telemetry spans (no associated run)
oc exec deployment/observatory -- sqlite3 /data/observatory.db \
  "DELETE FROM telemetry_spans WHERE pipeline_run_id IS NULL AND created_at < datetime('now', '-30 days');"

# Reclaim disk space after large deletes
oc exec deployment/observatory -- sqlite3 /data/observatory.db VACUUM
```

### Cascading deletes

The schema uses `ON DELETE CASCADE` on foreign keys, so deleting a pipeline run automatically removes its:
- `telemetry_spans`
- `telemetry_summaries`
- `run_commands`, `run_packages`, `run_containers`

Deleting a pipeline cascades to all its runs and their child records.
