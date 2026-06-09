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

- **Backend**: FastAPI + SQLite (aiosqlite)
- **Frontend**: React 18 + TypeScript + Tailwind CSS + Vite
- **Dev**: Honcho + Procfile for local multi-process dev
- **Verification**: Claude Code + Codex skills for agentic evidence gathering

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
    └── verify-claims.py           → claim_verdicts
        ├── --mode deterministic       (Vertex AI SDK, hardcoded evidence)
        ├── --mode agentic             (Claude Code skill, self-directed evidence)
        └── --engine codex             (Codex skill, cross-engine comparison)
```

Run `make pipeline` to execute all 9 steps in sequence, or `make help` to see all targets.

## Make Targets

| Target | Description |
|--------|-------------|
| `make dev` | Start backend + frontend via Honcho |
| `make seed` | Seed database from org-pulse-config.json (needs backend running) |
| `make collect-artifacts` | Download CI artifacts, data repos, source repos, job traces |
| `make ingest-definitions` | Parse .gitlab-ci.yml into DB |
| `make ingest-telemetry` | Parse OTEL cost/token data into DB |
| `make parse-traces` | Parse job traces into structured JSON |
| `make ingest-traces` | Load parsed traces + OTEL events into DB |
| `make extract-claims` | Extract factual claims from artifacts (Vertex AI) |
| `make ingest-claims` | Load extracted claims into DB |
| `make verify-claims` | Verify claims — deterministic mode (Vertex AI) |
| `make verify-claims-agentic` | Verify claims — agentic mode (Claude Code skill) |
| `make verify-claims-retry` | Re-verify insufficient/inconclusive claims agentically |
| `make pipeline` | Run full 9-step data pipeline |
| `make clear-verdicts` | Reset verification data for re-run |
| `make help` | Show all targets |

## Monitored Pipelines

| Pipeline | Group | Description |
|----------|-------|-------------|
| rfe-assessor | RFEs | Scores RFE quality against rubric |
| rfe-autofixer | RFEs | Rewrites RFEs to improve scores |
| strat-pipeline | Strats | Generates strategy documents from RFEs |
| strat-security-reviews | Strats | Security reviews of strategy proposals |
| epic-decomposer | Strats | Decomposes strategies into epics |
| test-plan-generator | Strats | Generates test plans from strategies |
| autofix | Bugs | Automated bug fixes |

## Pages

| Page | Path | Description |
|------|------|-------------|
| Status Board | `/` | Pipeline health dashboard with grouped cards |
| Pipeline Detail | `/pipelines/:slug` | Run history, charts, CI config, artifacts |
| Artifacts | `/artifacts` | Cross-pipeline file browser with content viewer |
| Telemetry | `/telemetry` | Cost, tokens, run metrics, model dimensions |
| Provenance | `/provenance` | Package and container inventory |
| Hallucinations | `/hallucinations` | Claim verification, triage (By Claim + By Issue tabs) |
| Traces | `/agent-traces` | Agent execution events, tool usage |

## Hallucination Detection

The hallucination detection system extracts verifiable factual claims from AI-generated pipeline outputs, verifies them against architecture documentation, and presents results for triage. See [ADR-0018](docs/decisions/ADR-0018-hallucination-detection.md) and [ADR-0025](docs/decisions/ADR-0025-agentic-evidence-gathering.md).

### Three-stage pipeline

1. **Extract** — LLM (Claude Sonnet via Vertex AI) decomposes artifact markdown into atomic verifiable claims using the [Claimify](https://arxiv.org/abs/2502.10855) methodology
2. **Verify** — agentic verification via Claude Code or Codex skill (`.claude/skills/verify-claim/SKILL.md`):
   - Reads warmup evidence (co-located source text, NFR checklist)
   - Queries [arch-query](https://github.com/opendatahub-io/architecture-context) for component facts, ports, webhooks, dependencies, CRDs
   - Reads raw architecture docs with `-o raw` for data flows and deployment topology
   - Checks overlays for recent architecture changes
   - Classifies root cause for refuted claims
3. **Triage** — UI with search, source file filter, type/verdict filters, sortable columns, verification log viewer

### Verification modes

```bash
# Deterministic: hardcoded evidence gathering, single LLM judge call
python scripts/verify-claims.py

# Agentic (Claude): skill-driven, LLM decides what to look up
python scripts/verify-claims.py --mode agentic --agentic-model opus

# Agentic (Codex): same skill, different engine for cross-comparison
python scripts/verify-claims.py --mode agentic --engine codex

# Re-verify only insufficient/inconclusive claims
python scripts/verify-claims.py --mode agentic-retry

# Single claim
python scripts/verify-claims.py --claim 4682 --mode agentic
```

### Verdicts

- **Supported** — evidence confirms the claim (for proposals: source text describes it)
- **Refuted** — evidence contradicts the claim (for proposals: reviewer mischaracterized it)
- **Insufficient** — no relevant evidence found even after tool queries
- **Inconclusive** — evidence is ambiguous

### Key findings

The system has surfaced several classes of findings (see [hallucination-findings.md](docs/notes/hallucination-findings.md)):

- **Reviewer hallucinations** — security reviewers inject training knowledge not in source material (fabricated version numbers, invented library details)
- **Source confusion** — reviewers state proposed features as existing platform facts
- **NFR checklist gaps** — the human-authored ground truth is imprecise, causing downstream hallucinations
- **Architecture doc errors** — AI-generated architecture docs contain factual errors (auth chain misattribution)
- **Compliance findings** — verification discovered spark-operator using CGO_ENABLED=0 (non-FIPS-compliant build flags)
- **Cross-engine disagreement** — Claude and Codex produce different verdicts on complex architectural claims, useful as a triage signal

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
| [0022](docs/decisions/ADR-0022-single-verdict-per-claim.md) | Single verdict per claim (aggregated evidence) |
| [0023](docs/decisions/ADR-0023-skip-boilerplate-claims.md) | Skip boilerplate claims during extraction |
| [0024](docs/decisions/ADR-0024-hallucination-root-cause-tracing.md) | Root cause tracing via execution logs |
| [0025](docs/decisions/ADR-0025-agentic-evidence-gathering.md) | Agentic evidence gathering via Claude Code/Codex skills |

## License

Internal — Red Hat AI
