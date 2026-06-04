# Phase 7: Polish + Deployment

**Estimate:** 2-3 days
**Milestone:** M6-production

## Goal

Production deployment, authentication, data retention, documentation.

## Deliverables

- OpenShift deployment manifests (Kustomize)
- OAuth proxy or API key auth for push endpoints (OTLP, MLflow, SBOM)
- Retention/purge background job (telemetry_spans 90d, provenance 180d, SBOMs kept)
- User documentation (how to read the dashboard, what each view shows)
- Runbook for operations (how to deploy, backup, restore, troubleshoot)
- `run-manifest.json` schema documentation + example snippet for pipeline owners

## Tasks

- `task-openshift-manifests.md`
- `task-auth-for-push-endpoints.md`
- `task-retention-purge-job.md`
- `task-user-documentation.md`
- `task-runbook.md`
- `task-manifest-schema-docs.md`

## Exit Criteria

- Deployed and running on target platform
- Push endpoints require authentication
- Retention job runs on schedule and purges old data
- Documentation exists for users, operators, and pipeline owners
