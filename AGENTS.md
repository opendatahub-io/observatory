# Agents: Agentic CI Observatory

## Project Overview

Observatory is a lightweight observability platform for the RHAI AI-First pipeline infrastructure. FastAPI backend, React frontend, SQLite database, single container deployment.

## Coding Standards

### Backend (Python / FastAPI)

- Python 3.11+
- FastAPI with async endpoints
- Pydantic v2 for request/response models
- SQLite in WAL mode via aiosqlite
- Alembic for schema migrations
- Type hints on all function signatures
- No comments unless explaining a non-obvious constraint
- Tests: pytest + httpx AsyncClient

### Frontend (React)

- TypeScript, strict mode
- Functional components with hooks
- Recharts or Chart.js for visualizations
- No CSS frameworks — plain CSS modules or Tailwind (decide in ADR)
- Tests: vitest + React Testing Library

### General

- No unused imports, no dead code
- No feature flags or backwards-compat shims
- Prefer editing existing files over creating new ones
- One concern per file, one responsibility per function

## Repository Conventions

- `PLAN.md` is an index — do not put prose plans in it
- Design details live in `docs/plans/phase-*.md`
- Tasks live in `docs/tasks/{pending,current,blocked,done}/`
- Bugs live in `docs/bugs/{open,fixed,wontfix}/`
- Architectural decisions live in `docs/decisions/ADR-*.md`
- Session activity goes in `docs/notes/session-log.md`

## Testing Requirements

- Every API endpoint must have at least one happy-path test
- Database operations must be tested against a real SQLite instance (no mocks)
- Frontend components with logic must have tests

## Workflow

1. Read this file and `PLAN.md`
2. Pick a task from `docs/tasks/pending/`
3. Check its `blockedBy` — skip if blocked
4. Move it to `docs/tasks/current/`
5. Do the work
6. Record discoveries in the task file under Notes
7. Create bug files in `docs/bugs/open/` if issues found
8. Create ADRs in `docs/decisions/` for architectural choices
9. Move task to `docs/tasks/done/`
10. Update `PLAN.md` links
11. Append to `docs/notes/session-log.md`

## Ownership

- Backend API + collector: any agent
- Frontend React: any agent
- Schema migrations: coordinate — only one agent at a time
- PLAN.md: coordinator agent only
