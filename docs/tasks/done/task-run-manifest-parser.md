# Task: Run Manifest Parser

## Goal

Parse `run-manifest.json` artifacts and populate provenance tables (commands, packages, containers).

## Context

The run manifest is the preferred way to get provenance data. See PLAN.md "Provenance Ingestion" section for the schema. As a fallback, also extract container image refs from CI API job definitions when no manifest is present.

## Acceptance Criteria

- [ ] Parse `run-manifest.json` v1 schema
- [ ] Insert commands into `run_commands` (ordered by step)
- [ ] Insert packages into `run_packages` (grouped by manager)
- [ ] Insert containers into `run_containers` (with digest if available)
- [ ] Fallback: extract container image from GitLab CI job `image` field when no manifest
- [ ] Associate all records with correct `pipeline_run_id`
- [ ] Tests with sample manifest data

## Files Likely Involved

- backend/collector/parsers/manifest.py
- tests/test_manifest_parser.py

## Phase

3 — Artifact Scraping

## Blocked By

- task-gitlab-artifact-download.md

## Status

Pending
