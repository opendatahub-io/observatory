# Task: React App Shell

## Goal

Create the React application shell: routing, layout, navigation, and build pipeline that produces static files served by FastAPI.

## Context

The React app is served as static files from the FastAPI container. It needs client-side routing and a nav layout that all views share.

## Acceptance Criteria

- [ ] React app with TypeScript strict mode
- [ ] Client-side routing (React Router): `/`, `/pipelines/:slug`, `/telemetry`, `/admin`
- [ ] Shared layout: header with nav links, main content area
- [ ] Build produces static files in a known output directory
- [ ] FastAPI serves the static build and falls back to index.html for client routes
- [ ] Dev server with hot reload for frontend development

## Files Likely Involved

- frontend/src/App.tsx
- frontend/src/main.tsx
- frontend/src/components/Layout.tsx
- frontend/package.json
- frontend/vite.config.ts

## Phase

1 — Core API + Static Inventory

## Blocks

- task-status-board-ui.md
- task-pipeline-detail-ui.md

## Status

Pending
