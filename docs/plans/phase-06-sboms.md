# Phase 6: SBOMs + Vulnerability Scanning

**Estimate:** 3-4 days
**Milestone:** M5-provenance

## Goal

Container SBOM generation, storage, and vulnerability scanning. Cross-pipeline provenance views for packages and containers.

## Deliverables

- SBOM push endpoint (`POST /api/sboms`) for pipelines with pre-generated SBOMs
- Background job: run `syft` against new image digests seen in `run_containers`
- Background job: run `grype` against stored SBOMs for vulnerability detection
- `container_sboms` + `sbom_vulnerabilities` storage and query API
- SBOM viewer UI (package list from SBOM, vulnerability badges per package)
- Cross-pipeline package inventory view (which pipelines use what, version drift)
- Cross-pipeline container inventory view (all images in use, SBOM availability)
- Vulnerability dashboard (severity breakdown, affected pipelines, CVE list)
- Provenance diff view (compare two runs of the same pipeline)

## Tasks

- `task-sbom-push-endpoint.md`
- `task-sbom-generation-job.md`
- `task-vulnerability-scanning-job.md`
- `task-sbom-viewer-ui.md`
- `task-package-inventory-ui.md`
- `task-container-inventory-ui.md`
- `task-vulnerability-dashboard-ui.md`
- `task-provenance-diff-ui.md`

## Exit Criteria

- SBOMs generated or received for at least one container image
- Vulnerability scan results stored and queryable
- Package inventory shows cross-pipeline version data
- Vulnerability dashboard shows severity breakdown
- Diff view shows changes between two runs
