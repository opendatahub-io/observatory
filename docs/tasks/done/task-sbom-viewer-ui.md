# Task: SBOM Viewer UI

## Goal

View the full SBOM for a container image: package list, vulnerability badges.

## Acceptance Criteria

- [ ] Accessible from container inventory or run detail containers table
- [ ] Package list from SBOM (name, version, type)
- [ ] Vulnerability badges per package (severity color)
- [ ] Summary: total packages, total vulnerabilities by severity
- [ ] Link to CVE details for each vulnerability

## Files Likely Involved

- frontend/src/pages/SBOMViewer.tsx
- frontend/src/components/SBOMPackageList.tsx
- frontend/src/components/VulnBadge.tsx

## Phase

6 — SBOMs + Vulnerability Scanning

## Blocked By

- task-sbom-push-endpoint.md

## Status

Pending
