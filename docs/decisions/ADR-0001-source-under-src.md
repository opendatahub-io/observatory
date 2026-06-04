# ADR-0001: Move Source Directories Under ./src

## Status

Accepted

## Context

The project currently has `backend/` and `frontend/` at the repository root alongside docs, config files, k8s manifests, and other non-source artifacts. This makes the root cluttered and doesn't clearly separate source code from project infrastructure.

## Decision

Move all source-related directories under `./src/`:

- `backend/` → `src/backend/`
- `frontend/` → `src/frontend/`
- `alembic/` → `src/alembic/`
- `tests/` → `src/tests/`
- `schemas/` → `src/schemas/`

Non-source directories stay at root: `docs/`, `data/`, `k8s/`.

## Consequences

Positive:
- Clear separation between source code and project infrastructure
- Standard Python `src/` layout prevents accidental imports of uninstalled packages
- Easier to reason about what gets built vs. what supports the build

Negative:
- One-time update to pyproject.toml, Dockerfile, alembic.ini, and config defaults
- All existing imports (`from backend.xxx`) remain unchanged — only the package discovery path changes
