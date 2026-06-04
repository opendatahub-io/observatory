# Agentic CI Observatory

Observability platform for RHAI AI-First pipeline infrastructure. Monitors agentic CI pipelines, collects artifacts and execution traces, analyzes telemetry, and detects hallucinations in AI-generated outputs.

## Quick Start

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
npm install --prefix src/frontend

# Configure
cp .env.example .env  # edit with your tokens

# Start dev stack
make dev
```

Open http://localhost:5173

## Architecture

- **Backend**: FastAPI + SQLite (aiosqlite) + Alembic migrations
- **Frontend**: React 18 + TypeScript + Tailwind CSS + Vite
- **Dev**: Honcho + Procfile for local multi-process dev

## Data Pipeline

```
GitLab/GitHub CI
    │
    ├── Collector (background)     → pipeline_runs, health status
    │
    ├── collect-artifacts.py       → ./var/artifacts/
    │   ├── CI job artifact ZIPs       (extracted files)
    │   ├── Data repo clones           (git clone)
    │   ├── Source/skill/lib repos     (git clone)
    │   └── Job traces                 (GitLab API)
    │
    ├── ingest-definitions.py      → ci_jobs, ci_includes
    ├── ingest-telemetry.py        → telemetry_summaries, telemetry_dimensions
    ├── parse-job-traces.py        → ./var/traces/ (JSON)
    ├── ingest-traces.py           → trace_events, trace_packages, trace_metadata
    │
    ├── extract-claims.py          → ./var/claims/ (JSON, via Vertex AI)
    ├── ingest-claims.py           → claims, claim_sources, claim_jira_keys
    └── verify-claims.py           → claim_verdicts (via Vertex AI + arch-query)
```

## Make Targets

| Target | Description |
|--------|-------------|
| `make dev` | Start backend + frontend via Honcho |
| `make backend` | Start backend only |
| `make frontend` | Start frontend only |
| `make seed` | Seed database from org-pulse-config.json |
| `make test` | Run pytest |
| `make lint` | Run ruff |
| `make collect-artifacts` | Download CI artifacts, data repos, source repos, job traces |
| `make ingest-definitions` | Parse .gitlab-ci.yml into DB |
| `make ingest-telemetry` | Parse OTEL cost/token data into DB |
| `make parse-traces` | Parse job traces into structured JSON |
| `make ingest-traces` | Load parsed traces + OTEL events into DB |
| `make extract-claims` | Extract factual claims from artifacts (Vertex AI) |
| `make ingest-claims` | Load extracted claims into DB |
| `make verify-claims` | Verify claims against source material (Vertex AI) |
| `make clear-verdicts` | Reset verification data for re-run |

## Pages

| Page | Path | Description |
|------|------|-------------|
| Status Board | `/` | Pipeline health dashboard with grouped cards |
| Pipeline Detail | `/pipelines/:slug` | Run history, charts, CI config, artifacts |
| Artifacts | `/artifacts` | Cross-pipeline file browser with content viewer |
| Telemetry | `/telemetry` | Cost, tokens, run metrics, model dimensions |
| Provenance | `/provenance` | Package and container inventory |
| Vulnerabilities | `/vulnerabilities` | Cross-pipeline vulnerability dashboard |
| Hallucinations | `/hallucinations` | Claim extraction, verification, triage |
| Traces | `/agent-traces` | Agent execution events, tool usage |
| Collector | `/collector` | Collector health and log viewer |
| Admin | `/admin` | Pipeline CRUD, DB health, API keys, credentials |

## Hallucination Detection

The hallucination detection system extracts verifiable factual claims from AI-generated pipeline outputs, verifies them against source material, and presents results for triage.

### Pipeline

1. **Extract** — LLM decomposes artifact markdown into atomic verifiable claims
2. **Verify** — LLM-as-judge evaluates claims against evidence:
   - Co-located source text (strat text, RFE originals)
   - Architecture context via [arch-query](https://github.com/opendatahub-io/architecture-context)
   - NFR security checklist
   - Active architecture overlays
3. **Triage** — UI with search, filters, sortable columns, verification logs

### Verdicts

- **Supported** — evidence confirms the claim
- **Refuted** — evidence contradicts the claim (potential hallucination)
- **Insufficient** — no relevant evidence found
- **Inconclusive** — evidence is ambiguous

Uses Claude Sonnet for initial verification with automatic escalation to Claude Opus for low-confidence results.

## References

The hallucination detection design draws from these sources:

### Academic Papers

- Farquhar, S., Kossen, J., Kuhn, L., & Gal, Y. (2024). Detecting hallucinations in large language models using semantic entropy. *Nature*, 630, 625-630. https://doi.org/10.1038/s41586-024-07421-0

- Kossen, J., Han, J., Gal, Y., & Farquhar, S. (2024). Semantic entropy probes: Robust and cheap hallucination detection in LLMs. https://arxiv.org/abs/2406.15927

- Metropolitansky, B. & Larson, K. (2025). Claimify: Factual claim extraction for LLM evaluation. *Proceedings of ACL 2025*.

- Metropolitansky, B. & Larson, K. (2026). VeriTrail: Closed-domain hallucination detection with traceability for multi-generative-step processes. *Proceedings of ICLR 2026*.

### Industry Resources

- Braintrust. (2026). Best hallucination detection tools for LLM applications: Catch bad outputs before users do. https://www.braintrust.dev/articles/hallucination-detection-tools

- Datadog. (2024). Detecting hallucinations with LLM-as-a-judge: Prompt engineering and beyond. https://www.datadoghq.com/blog/hallucination-detection-llm-as-judge/

### Open Source

- Exa Hallucination Detector — three-stage pipeline (extract → search → verify) reference implementation. https://github.com/exa-labs/exa-hallucination-detector

- Architecture Context — RHOAI component architecture documentation and query tool. https://github.com/opendatahub-io/architecture-context

## ADRs

| ADR | Decision |
|-----|----------|
| [0009](docs/decisions/ADR-0009-honcho-for-local-dev.md) | Honcho + Procfile for local dev |
| [0010](docs/decisions/ADR-0010-tailwind-sidebar-dark-mode.md) | Tailwind CSS, sidebar layout, dark mode |
| [0011](docs/decisions/ADR-0011-raw-artifact-collection.md) | Raw artifact collection to filesystem |
| [0012](docs/decisions/ADR-0012-pipeline-definition-collection.md) | Pipeline definition collection |
| [0013](docs/decisions/ADR-0013-ci-definition-ingestion.md) | CI definition ingestion to DB |
| [0014](docs/decisions/ADR-0014-global-artifacts-viewer.md) | Global artifacts viewer page |
| [0015](docs/decisions/ADR-0015-telemetry-tier1-run-metrics.md) | Telemetry Tier 1 — run metrics |
| [0016](docs/decisions/ADR-0016-telemetry-tier2-otel-ingestion.md) | Telemetry Tier 2 — OTEL ingestion |
| [0017](docs/decisions/ADR-0017-model-telemetry.md) | Model usage telemetry |
| [0018](docs/decisions/ADR-0018-hallucination-detection.md) | Hallucination detection system |
| [0019](docs/decisions/ADR-0019-full-otel-event-ingestion.md) | Full OTEL event log ingestion |
| [0020](docs/decisions/ADR-0020-gitlab-job-trace-collection.md) | GitLab job trace collection |
| [0021](docs/decisions/ADR-0021-job-trace-parsing.md) | Job trace parsing |

## License

Internal — Red Hat AI
