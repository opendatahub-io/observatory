# ADR-0009: Use Honcho and Procfile for Local Development

## Status

Accepted

## Context

The development workflow requires running two processes concurrently: the FastAPI backend (uvicorn) and the React frontend (vite dev server). Until now the only way to run the full stack locally was via `docker compose`, which means a full container image build on every change. The multi-stage Dockerfile (Node build stage + Python runtime stage) makes this especially slow — even with layer caching, any change to backend code or frontend source triggers a rebuild that takes tens of seconds. Fighting image layer cache invalidation during active development is tedious and breaks flow.

The vite dev server already has proxy rules configured to forward `/api/*`, `/v1/*`, `/mlflow/*`, `/healthz`, and `/metrics` to `localhost:8000`, so the two processes are designed to run side by side.

## Decision

Use [honcho](https://github.com/nickstenning/honcho) (a Python Procfile runner) with a `Procfile.dev` to run both processes in a single terminal for local development. Makefile targets provide the entry points.

`Procfile.dev`:
```
backend: PYTHONPATH=src .venv/bin/uvicorn backend.app:app --reload --reload-dir src/backend --host 127.0.0.1 --port 8000
frontend: npm run dev --prefix src/frontend
```

`make dev` starts both processes. `make backend` and `make frontend` start them individually.

Container builds (`docker compose`) remain the canonical way to produce and test the production image. Honcho is strictly for the inner development loop.

## Alternatives Considered

- **docker compose with volume mounts and --reload**: Still requires the initial image build, adds complexity with mount permissions, and vite HMR doesn't work well through a container proxy.
- **Two terminal tabs / tmux**: Works but requires manual coordination; easy to forget one process.
- **foreman (Ruby)**: Equivalent functionality but adds a Ruby dependency; honcho is Python-native and already lives in the project's venv.
- **overmind / hivemind (Go)**: More features (tmux integration, process restart) but an external binary to install. Overkill for two processes.

## Consequences

Positive:
- Sub-second feedback loop — uvicorn `--reload` and vite HMR both trigger on file save
- Single command (`make dev`) starts everything
- No container build during active development
- honcho is a pure-Python dev dependency with no system-level install required
- `.env` is loaded automatically by honcho

Negative:
- Developers need the Python venv and Node dependencies installed locally (vs. everything inside the container)
- Local environment may drift from the container — developers should still do a container build before pushing
