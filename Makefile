VENV := .venv/bin

.PHONY: help dev backend frontend seed test lint collect-artifacts ingest-definitions ingest-telemetry extract-claims ingest-claims verify-claims verify-claims-agentic verify-claims-retry clear-verdicts parse-traces ingest-traces pipeline

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

dev: ## Start backend + frontend via Honcho
	$(VENV)/honcho start -f Procfile.dev

backend: ## Start backend only (uvicorn with hot reload)
	PYTHONPATH=src $(VENV)/uvicorn backend.app:app --reload --reload-dir src/backend --host 127.0.0.1 --port 8000

frontend: ## Start frontend only (vite dev server)
	npm run dev --prefix src/frontend

seed: ## Seed/update pipelines from org-pulse-config.json (via API, needs backend running)
	@curl -sf -X POST http://localhost:8000/api/admin/seed | python3 -m json.tool || echo "ERROR: Backend not running. Start with 'make dev' first."

test: ## Run pytest
	$(VENV)/pytest

lint: ## Run ruff linter
	$(VENV)/ruff check src/

collect-artifacts: ## Download CI artifacts, data repos, source repos, job traces
	$(VENV)/python scripts/collect-artifacts.py

ingest-definitions: ## Parse .gitlab-ci.yml into DB
	$(VENV)/python scripts/ingest-definitions.py

ingest-telemetry: ## Parse OTEL cost/token data into DB
	$(VENV)/python scripts/ingest-telemetry.py

extract-claims: ## Extract factual claims from strat artifacts (Vertex AI)
	$(VENV)/python scripts/extract-claims.py strat-security-reviews strat-pipeline --workers 10

ingest-claims: ## Load extracted claims into DB
	$(VENV)/python scripts/ingest-claims.py

verify-claims: ## Verify claims against source material (Vertex AI, deterministic)
	$(VENV)/python scripts/verify-claims.py

verify-claims-agentic: ## Verify claims with agentic evidence gathering (Claude Code)
	$(VENV)/python scripts/verify-claims.py --mode agentic --workers 3

verify-claims-retry: ## Re-verify insufficient/inconclusive claims agentically
	$(VENV)/python scripts/verify-claims.py --mode agentic-retry --workers 3

parse-traces: ## Parse job traces into structured JSON
	$(VENV)/python scripts/parse-job-traces.py

ingest-traces: ## Load parsed traces + OTEL events into DB
	$(VENV)/python scripts/ingest-traces.py

pipeline: ## Run full data pipeline: collect → seed → ingest → parse → extract → verify
	@echo "=== 1/9 Collecting artifacts ==="
	$(VENV)/python scripts/collect-artifacts.py
	@echo "=== 2/9 Seeding database ==="
	@curl -sf -X POST http://localhost:8000/api/admin/seed | python3 -m json.tool || echo "WARNING: Backend not running, skipping seed"
	@echo "=== 3/9 Ingesting CI definitions ==="
	$(VENV)/python scripts/ingest-definitions.py
	@echo "=== 4/9 Ingesting telemetry ==="
	$(VENV)/python scripts/ingest-telemetry.py
	@echo "=== 5/9 Parsing job traces ==="
	$(VENV)/python scripts/parse-job-traces.py
	@echo "=== 6/9 Ingesting traces ==="
	$(VENV)/python scripts/ingest-traces.py
	@echo "=== 7/9 Extracting claims (Vertex AI) ==="
	$(VENV)/python scripts/extract-claims.py strat-security-reviews strat-pipeline --workers 10
	@echo "=== 8/9 Ingesting claims ==="
	$(VENV)/python scripts/ingest-claims.py
	@echo "=== 9/9 Verifying claims (Vertex AI) ==="
	$(VENV)/python scripts/verify-claims.py
	@echo "=== Pipeline complete ==="

clear-verdicts: ## Reset all verification data for re-run
	sqlite3 data/observatory.db "DELETE FROM claim_verdicts"
	rm -f var/verification/*.md
	@echo "Cleared verdicts and verification logs"
