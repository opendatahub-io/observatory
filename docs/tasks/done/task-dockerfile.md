# Task: Dockerfile

## Goal

Multi-stage Dockerfile that builds the React frontend and packages it with the FastAPI backend and SQLite into a single container.

## Acceptance Criteria

- [x] Stage 1: build React app (node, npm install, npm run build)
- [x] Stage 2: Python runtime with FastAPI, copy React build, copy backend code
- [x] Container starts FastAPI serving both API and static files
- [x] SQLite database created on persistent volume mount point (/data/)
- [x] Health check endpoint configured (curl /healthz every 30s)
- [x] Runs as non-root user (UID 1000)
- [x] `.dockerignore` excludes node_modules, __pycache__, .git, etc.

## Files Likely Involved

- Dockerfile
- .dockerignore

## Phase

1 — Core API + Static Inventory

## Status

Done
