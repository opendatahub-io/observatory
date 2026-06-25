# Chat Feature -- Deployment Wiring

The chat and knowledge base features require an LLM backend (Claude) for the conversational interface. Observatory supports two authentication modes: Vertex AI (recommended for this project) and direct Anthropic API key.

The knowledge base works independently -- it needs no LLM credentials. Only the chat endpoint (`POST /api/v1/chat/conversations/{id}/messages`) requires a configured LLM backend. If neither auth mode is configured, the endpoint returns `503`.

---

## Authentication Modes

### Vertex AI (recommended)

This project runs Claude through Google Vertex AI. Observatory follows the same credential pattern described in `docs/vertex-claude-runtime.md`: a GCP project ID, a region, and Google Application Default Credentials (ADC).

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID` | `""` | GCP project ID for Anthropic-on-Vertex. Setting this activates Vertex mode. |
| `OBSERVATORY_CLOUD_ML_REGION` | `us-east5` | Vertex AI region. |
| `GOOGLE_APPLICATION_CREDENTIALS` | _(none)_ | Path to the Google ADC JSON file. Standard GCP variable, no `OBSERVATORY_` prefix. |

When `OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID` is set, the chat agent creates an `AsyncAnthropicVertex` client that authenticates through Google ADC. The `GOOGLE_APPLICATION_CREDENTIALS` env var must point to a valid service account key or workload identity credential file.

### Direct Anthropic API

For environments without Vertex AI (local development, non-GCP clusters):

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `OBSERVATORY_ANTHROPIC_API_KEY` | `""` | Anthropic API key (`sk-ant-...`). Used only when Vertex project ID is not set. |

### Model selection

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `OBSERVATORY_CHAT_MODEL` | `claude-sonnet-4-20250514` | Claude model ID. For Vertex, use the standard model ID (not the `google-vertex-anthropic/` prefixed form -- the Anthropic Python SDK handles the translation). |

---

## Kubernetes

Observatory already uses `envFrom` to inject `observatory-config` (ConfigMap) and `observatory-secrets` (Secret) into the pod. The chat credentials slot into these existing resources.

### Add chat variables to the secret

The Vertex project ID and region are not sensitive, but they are deployment-specific. Adding them to the existing secret keeps the wiring simple (one `envFrom`).

Update `observatory-secrets` in `deploy/k8s/18-observatory.yaml` or create via CLI:

```bash
kubectl create secret generic observatory-secrets \
  -n ai-pipeline \
  --from-literal=OBSERVATORY_GITLAB_TOKEN='...' \
  --from-literal=OBSERVATORY_GITHUB_TOKEN='...' \
  --from-literal=OBSERVATORY_API_KEY='observatory-dev-key' \
  --from-literal=OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID="${ANTHROPIC_VERTEX_PROJECT_ID}" \
  --from-literal=OBSERVATORY_CLOUD_ML_REGION="${CLOUD_ML_REGION:-us-east5}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

The values can come from the same `.env` file used by `deploy/scripts/06-create-secrets.sh` for `pipeline-secrets`. The underlying GCP project and region are the same -- only the env var names differ (`ANTHROPIC_VERTEX_PROJECT_ID` vs `OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID`).

### Mount Google ADC credentials

The Observatory pod needs the same `gcp-credentials` secret that pipeline agent pods use. Add a volume and volume mount to the deployment:

```yaml
# In deploy/k8s/18-observatory.yaml, under spec.template.spec.containers[0]:
        env:
        - name: GOOGLE_APPLICATION_CREDENTIALS
          value: /var/run/secrets/gcp/credentials.json

        volumeMounts:
        - name: data
          mountPath: /data
        - name: gcp-credentials
          mountPath: /var/run/secrets/gcp
          readOnly: true

# Under spec.template.spec.volumes:
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: observatory-data
      - name: gcp-credentials
        secret:
          secretName: gcp-credentials
```

The `gcp-credentials` secret is the same one created by `deploy/scripts/11-create-gcp-credentials-secret.sh` and used by pipeline agent pods. If it already exists in the `ai-pipeline` namespace, no additional secret creation is needed.

### Full manifest diff

Here is what changes in `deploy/k8s/18-observatory.yaml`:

```diff
 # Secret
 stringData:
   OBSERVATORY_GITLAB_TOKEN: ""
   OBSERVATORY_GITHUB_TOKEN: ""
   OBSERVATORY_API_KEY: "observatory-dev-key"
+  OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID: ""
+  OBSERVATORY_CLOUD_ML_REGION: "us-east5"
+  OBSERVATORY_CHAT_MODEL: "claude-sonnet-4-20250514"

 # Deployment container
       containers:
       - name: observatory
         ...
+        env:
+        - name: GOOGLE_APPLICATION_CREDENTIALS
+          value: /var/run/secrets/gcp/credentials.json
+
         envFrom:
         - configMapRef:
             name: observatory-config
         - secretRef:
             name: observatory-secrets

         volumeMounts:
         - name: data
           mountPath: /data
+        - name: gcp-credentials
+          mountPath: /var/run/secrets/gcp
+          readOnly: true

       volumes:
       - name: data
         persistentVolumeClaim:
           claimName: observatory-data
+      - name: gcp-credentials
+        secret:
+          secretName: gcp-credentials
```

### Apply changes

```bash
# Update the secret with real values
kubectl apply -f deploy/k8s/18-observatory.yaml

# Or if modifying the running secret directly:
kubectl -n ai-pipeline patch secret observatory-secrets --type merge \
  -p "{\"stringData\":{\"OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID\":\"${ANTHROPIC_VERTEX_PROJECT_ID}\",\"OBSERVATORY_CLOUD_ML_REGION\":\"${CLOUD_ML_REGION:-us-east5}\"}}"

# Restart the pod to pick up changes
kubectl -n ai-pipeline rollout restart deployment/observatory
```

---

## Docker Compose (local development)

For local development with Vertex AI, mount the ADC credentials file and set the env vars in `compose.yaml`:

```yaml
services:
  observatory:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - observatory-data:/data
      - ${GOOGLE_APPLICATION_CREDENTIALS:-~/.config/gcloud/application_default_credentials.json}:/var/run/secrets/gcp/credentials.json:ro
    environment:
      - OBSERVATORY_GITLAB_TOKEN=${OBSERVATORY_GITLAB_TOKEN:-}
      - OBSERVATORY_GITHUB_TOKEN=${OBSERVATORY_GITHUB_TOKEN:-}
      - OBSERVATORY_API_KEY=observatory-dev-key
      - OBSERVATORY_CREDENTIAL_KEY=${OBSERVATORY_CREDENTIAL_KEY:-}
      - OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID=${ANTHROPIC_VERTEX_PROJECT_ID:-}
      - OBSERVATORY_CLOUD_ML_REGION=${CLOUD_ML_REGION:-us-east5}
      - GOOGLE_APPLICATION_CREDENTIALS=/var/run/secrets/gcp/credentials.json
    restart: unless-stopped

volumes:
  observatory-data:
```

For local development with a direct API key instead:

```yaml
    environment:
      - OBSERVATORY_ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
```

---

## Bare process (no containers)

For running the backend directly during development:

```bash
# Vertex AI (uses your local gcloud credentials)
export OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id"
export OBSERVATORY_CLOUD_ML_REGION="us-east5"
# GOOGLE_APPLICATION_CREDENTIALS is usually already set by gcloud auth,
# or point it at a service account key file.

# OR direct Anthropic API
export OBSERVATORY_ANTHROPIC_API_KEY="sk-ant-..."

# Optional: override the model
export OBSERVATORY_CHAT_MODEL="claude-sonnet-4-20250514"

# Start the backend
uv run uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

If using `gcloud` locally, ensure ADC is configured:

```bash
gcloud auth application-default login
```

This writes credentials to `~/.config/gcloud/application_default_credentials.json`, which the Anthropic Vertex SDK finds automatically without needing `GOOGLE_APPLICATION_CREDENTIALS`.

---

## Verification

### Check the pod environment

```bash
kubectl -n ai-pipeline exec deployment/observatory -- env | grep -E 'OBSERVATORY_(ANTHROPIC|CLOUD_ML|CHAT)|GOOGLE_APPLICATION'
```

Expected output (Vertex mode):

```
OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID=your-project-id
OBSERVATORY_CLOUD_ML_REGION=us-east5
OBSERVATORY_CHAT_MODEL=claude-sonnet-4-20250514
GOOGLE_APPLICATION_CREDENTIALS=/var/run/secrets/gcp/credentials.json
```

### Check the credential file exists

```bash
kubectl -n ai-pipeline exec deployment/observatory -- test -f /var/run/secrets/gcp/credentials.json && echo "OK" || echo "MISSING"
```

### Test the chat endpoint

```bash
# Create a conversation
CONV=$(curl -s -X POST http://localhost:8000/api/v1/chat/conversations \
  -H 'Content-Type: application/json' \
  -d '{"title": "test"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Send a message (should stream SSE events)
curl -N -X POST "http://localhost:8000/api/v1/chat/conversations/${CONV}/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content": "How many pipelines are tracked?"}'
```

If credentials are missing, the response is:

```json
{"detail": "Chat is not configured: set OBSERVATORY_ANTHROPIC_API_KEY or OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID"}
```

### Test the knowledge base (no credentials needed)

```bash
# Create a category
curl -s -X POST http://localhost:8000/api/v1/kb/categories \
  -H 'Content-Type: application/json' \
  -d '{"name": "General", "description": "General knowledge base articles"}'

# Create an article
curl -s -X POST http://localhost:8000/api/v1/kb/articles \
  -H 'Content-Type: application/json' \
  -d '{"title": "Getting Started", "body": "# Welcome\n\nThis is the Observatory knowledge base."}'
```
