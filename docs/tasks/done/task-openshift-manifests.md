# Task: OpenShift Deployment Manifests

## Goal

Kustomize manifests for deploying Observatory to OpenShift.

## Acceptance Criteria

- [ ] Deployment with single replica
- [ ] PVC for SQLite database
- [ ] Service + Route (with TLS)
- [ ] ConfigMap for non-secret config
- [ ] Secret for tokens (GITLAB_TOKEN, GITHUB_TOKEN, API keys)
- [ ] Health check probes (liveness, readiness)
- [ ] Resource limits (100m/256Mi steady, 500m/512Mi burst)
- [ ] Kustomize overlays for dev/prod

## Files Likely Involved

- k8s/base/deployment.yaml
- k8s/base/service.yaml
- k8s/base/pvc.yaml
- k8s/base/kustomization.yaml
- k8s/overlays/prod/kustomization.yaml

## Phase

7 — Polish + Deployment

## Status

Pending
