# Agentic CI Observatory — Project Plan

**Status:** M8 pending
**Current Milestone:** [M8-hallucination-detection](docs/milestones/M8-hallucination-detection.md) — Hallucination detection system
**Full Design:** [agentic-ci-observatory.md](agentic-ci-observatory.md)

---

## Milestones

- [M1-bootstrap](docs/milestones/M1-bootstrap.md) — App exists, pipeline CRUD, seeded data, grey status board
- [M2-live-status](docs/milestones/M2-live-status.md) — Collector running, real health indicators
- [M3-telemetry](docs/milestones/M3-telemetry.md) — Artifact scraping, telemetry dashboard, provenance tab
- [M4-push-receivers](docs/milestones/M4-push-receivers.md) — OTLP + MLflow push endpoints, trace explorer
- [M5-provenance](docs/milestones/M5-provenance.md) — SBOMs, vulnerability scanning, package/container inventory
- [M6-production](docs/milestones/M6-production.md) — Deployed, secured, documented
- [M7-frontend-redesign](docs/milestones/M7-frontend-redesign.md) — Sidebar layout + Tailwind CSS + dark mode
- [M8-hallucination-detection](docs/milestones/M8-hallucination-detection.md) — Claim extraction, verification, triage UI

---

## Phases

- [Phase 1: Core API + Static Inventory](docs/plans/phase-01-core-api.md) (3-4 days)
- [Phase 2: Pull Collector + Live Status](docs/plans/phase-02-pull-collector.md) (3-4 days)
- [Phase 3: Artifact Scraping — OTEL + MLflow + Provenance](docs/plans/phase-03-artifact-scraping.md) (4-5 days)
- [Phase 4: OTLP Push Receiver](docs/plans/phase-04-otlp-receiver.md) (2-3 days)
- [Phase 5: MLflow Push Receiver](docs/plans/phase-05-mlflow-receiver.md) (2-3 days)
- [Phase 6: SBOMs + Vulnerability Scanning](docs/plans/phase-06-sboms.md) (3-4 days)
- [Phase 7: Polish + Deployment](docs/plans/phase-07-deployment.md) (2-3 days)

**Total estimate:** 22-28 days

- [Phase 8: Claim Assurance and Improvement Loop](docs/plans/phase-08-claim-assurance.md)

---

## Active Tasks

- [task-claim-assurance-loop.md](docs/tasks/done/task-claim-assurance-loop.md) — Claimify-aligned extraction assurance, provenance, and feedback loop (complete)

### M8: Hallucination Detection

- [task-hallucination-poc.md](docs/tasks/pending/task-hallucination-poc.md) — Proof of concept on sample artifacts
- [task-hallucination-db-schema.md](docs/tasks/pending/task-hallucination-db-schema.md) — claims + claim_verdicts tables
- [task-hallucination-extraction.md](docs/tasks/pending/task-hallucination-extraction.md) — Batch claim extraction script
- [task-hallucination-verification.md](docs/tasks/pending/task-hallucination-verification.md) — Claim verification against source material
- [task-hallucination-api.md](docs/tasks/pending/task-hallucination-api.md) — REST API endpoints
- [task-hallucination-ui.md](docs/tasks/pending/task-hallucination-ui.md) — /hallucinations page + triage UI

---

## Completed Tasks

### Phase 1: Core API + Static Inventory (COMPLETE)

- [task-fastapi-project-structure.md](docs/tasks/done/task-fastapi-project-structure.md)
- [task-sqlite-schema-and-migrations.md](docs/tasks/done/task-sqlite-schema-and-migrations.md)
- [task-pipeline-crud-api.md](docs/tasks/done/task-pipeline-crud-api.md)
- [task-pipeline-metadata-api.md](docs/tasks/done/task-pipeline-metadata-api.md)
- [task-react-app-shell.md](docs/tasks/done/task-react-app-shell.md)
- [task-status-board-ui.md](docs/tasks/done/task-status-board-ui.md)
- [task-pipeline-detail-ui.md](docs/tasks/done/task-pipeline-detail-ui.md)
- [task-seed-data-loader.md](docs/tasks/done/task-seed-data-loader.md)
- [task-dockerfile.md](docs/tasks/done/task-dockerfile.md)
- [task-prometheus-metrics.md](docs/tasks/done/task-prometheus-metrics.md)

---

### Phase 2: Pull Collector + Live Status (COMPLETE)

- [task-background-collector.md](docs/tasks/done/task-background-collector.md)
- [task-gitlab-ci-integration.md](docs/tasks/done/task-gitlab-ci-integration.md)
- [task-github-actions-integration.md](docs/tasks/done/task-github-actions-integration.md)
- [task-health-status-computation.md](docs/tasks/done/task-health-status-computation.md)
- [task-run-history-api.md](docs/tasks/done/task-run-history-api.md)
- [task-status-board-live.md](docs/tasks/done/task-status-board-live.md)
- [task-run-history-ui.md](docs/tasks/done/task-run-history-ui.md)
- [task-collector-admin-ui.md](docs/tasks/done/task-collector-admin-ui.md)

---

## Pending Tasks

### Phase 3: Artifact Scraping + Provenance (COMPLETE)

- [task-gitlab-artifact-download.md](docs/tasks/done/task-gitlab-artifact-download.md)
- [task-otel-summary-parser.md](docs/tasks/done/task-otel-summary-parser.md)
- [task-mlflow-artifact-parser.md](docs/tasks/done/task-mlflow-artifact-parser.md)
- [task-run-manifest-parser.md](docs/tasks/done/task-run-manifest-parser.md)
- [task-telemetry-api.md](docs/tasks/done/task-telemetry-api.md)
- [task-provenance-api.md](docs/tasks/done/task-provenance-api.md)
- [task-telemetry-dashboard-ui.md](docs/tasks/done/task-telemetry-dashboard-ui.md)
- [task-provenance-tab-ui.md](docs/tasks/done/task-provenance-tab-ui.md)

### Phase 4: OTLP Push Receiver (COMPLETE)

- [task-otlp-receiver-endpoint.md](docs/tasks/done/task-otlp-receiver-endpoint.md)
- [task-span-pipeline-correlation.md](docs/tasks/done/task-span-pipeline-correlation.md)
- [task-trace-explorer-ui.md](docs/tasks/done/task-trace-explorer-ui.md)

### Phase 5: MLflow Push Receiver (COMPLETE)

- [task-mlflow-api-endpoints.md](docs/tasks/done/task-mlflow-api-endpoints.md)
- [task-mlflow-dashboard-ui.md](docs/tasks/done/task-mlflow-dashboard-ui.md)

### Phase 6: SBOMs + Vulnerability Scanning (COMPLETE)

- [task-sbom-push-endpoint.md](docs/tasks/done/task-sbom-push-endpoint.md)
- [task-sbom-generation-job.md](docs/tasks/done/task-sbom-generation-job.md)
- [task-vulnerability-scanning-job.md](docs/tasks/done/task-vulnerability-scanning-job.md)
- [task-sbom-viewer-ui.md](docs/tasks/done/task-sbom-viewer-ui.md)
- [task-package-inventory-ui.md](docs/tasks/done/task-package-inventory-ui.md)
- [task-container-inventory-ui.md](docs/tasks/done/task-container-inventory-ui.md)
- [task-vulnerability-dashboard-ui.md](docs/tasks/done/task-vulnerability-dashboard-ui.md)
- [task-provenance-diff-ui.md](docs/tasks/done/task-provenance-diff-ui.md)

### Phase 7: Polish + Deployment (COMPLETE)

- [task-openshift-manifests.md](docs/tasks/done/task-openshift-manifests.md)
- [task-auth-for-push-endpoints.md](docs/tasks/done/task-auth-for-push-endpoints.md)
- [task-retention-purge-job.md](docs/tasks/done/task-retention-purge-job.md)
- [task-user-documentation.md](docs/tasks/done/task-user-documentation.md)
- [task-runbook.md](docs/tasks/done/task-runbook.md)
- [task-manifest-schema-docs.md](docs/tasks/done/task-manifest-schema-docs.md)

---

## Open Bugs

None yet.

---

## Decisions

None yet.

---

## Notes

- [Session Log](docs/notes/session-log.md)
