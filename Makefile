VENV := .venv/bin

.PHONY: dev backend frontend seed test lint collect-artifacts ingest-definitions ingest-telemetry extract-claims ingest-claims verify-claims clear-verdicts parse-traces ingest-traces

dev:
	$(VENV)/honcho start -f Procfile.dev

backend:
	PYTHONPATH=src $(VENV)/uvicorn backend.app:app --reload --reload-dir src/backend --host 127.0.0.1 --port 8000

frontend:
	npm run dev --prefix src/frontend

seed:
	PYTHONPATH=src $(VENV)/python -m backend.seed

test:
	$(VENV)/pytest

lint:
	$(VENV)/ruff check src/

collect-artifacts:
	$(VENV)/python scripts/collect-artifacts.py

ingest-definitions:
	$(VENV)/python scripts/ingest-definitions.py

ingest-telemetry:
	$(VENV)/python scripts/ingest-telemetry.py

extract-claims:
	$(VENV)/python scripts/extract-claims.py strat-security-reviews strat-pipeline

ingest-claims:
	$(VENV)/python scripts/ingest-claims.py

verify-claims:
	$(VENV)/python scripts/verify-claims.py

parse-traces:
	$(VENV)/python scripts/parse-job-traces.py

ingest-traces:
	$(VENV)/python scripts/ingest-traces.py

clear-verdicts:
	sqlite3 data/observatory.db "DELETE FROM claim_verdicts"
	rm -f var/verification/*.md
	@echo "Cleared verdicts and verification logs"
