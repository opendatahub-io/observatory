# Plan: Authenticated `query_jira` with `.env`-based Credentials

> **Status: IMPLEMENTED (2026-07).** See "As-built notes" below for how the
> shipped code diverges from the plan. The plan text after that is preserved as
> the original design/review record.

## As-built notes

Targeting **Jira Cloud** (`*.atlassian.net`, basic auth with email + token).
What shipped, and where it differs from the plan:

- **Credentials** — three fields on `Settings` (`src/backend/config.py`):
  `jira_url`, `jira_email`, `jira_token`. Each uses a `validation_alias`
  (`AliasChoices`) so it accepts **both** the `OBSERVATORY_JIRA_*` names and the
  bare `JIRA_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` names Atlassian tooling
  conventionally uses. `.env` holds the bare names.
- **`env_file` was NOT added** to `model_config` (diverges from the plan's
  recommendation). Adding it made the *test suite* read the real `.env` and
  pick up live Jira creds, which is undesirable. Runtime instead relies on
  **honcho** loading `.env` for `make dev`. Trade-off: bare `make backend` still
  won't load `.env` — run under `make dev`, or export the vars, in that case.
- **Endpoint resolution** — the data-source row's endpoint wins if present;
  otherwise `settings.jira_url` is used. Adding a Jira data source is optional
  when `JIRA_URL` is set.
- **Cloud uses the current search API** — the classic `GET /rest/api/2/search`
  and `/rest/api/3/search` return **HTTP 410 Gone** on modern Jira Cloud. The
  cloud path calls **`GET /rest/api/3/search/jql`** (which requires **bounded**
  JQL — a bare `ORDER BY` yields HTTP 400) and gets an approximate `total` from
  **`POST /rest/api/3/search/approximate-count`**. Server/DC still uses
  `/rest/api/{api_version}/search` with a `total` in the body.
- **Auth default** — `basic` for `*.atlassian.net`, else `bearer`; overridable
  via the data source's `config.auth_type`.
- **`ssl_verify`** is honored (was hard-coded `verify=False`). Error text is
  scrubbed of the token via `_jira_scrub` before being surfaced.
- **Frontend** — no secret input; an amber hint on the Jira source form explains
  creds come from `.env` and to restart the backend after changes.
- **Tests** — `src/tests/test_jira_tool.py` covers cloud basic-auth header +
  `/search/jql` endpoint, server bearer + classic `/search`, unauthenticated
  fallback, not-configured error, cloud-requires-email, token scrubbing, and
  data-source endpoint override — all via a mocked `httpx` transport (no live
  Jira in CI).

## Goal

Let the chat agent query an **authenticated** Jira instance. The Jira endpoint
(and non-secret options) are defined on the Intelligence Settings page; the
**secret API token comes from `.env`**, exactly like the existing git tokens.

## Current state (what already exists)

- **The `query_jira` tool exists** (`src/backend/chat/tools.py:1524`,
  `_handle_query_jira`) and is wired into `_TOOL_HANDLERS`. It resolves the
  endpoint via `_resolve_endpoint(db, "jira")` and hits
  `GET {endpoint}/rest/api/2/search`. **It sends no `Authorization` header**, so
  it only works against an unauthenticated Jira.
- **Config is env-driven already.** `Settings` (`src/backend/config.py`) uses
  `env_prefix="OBSERVATORY_"`. `.env` already holds `OBSERVATORY_GITLAB_TOKEN`,
  `OBSERVATORY_GITHUB_TOKEN`, `OBSERVATORY_CREDENTIAL_KEY`, etc. Adding a Jira
  token is the same pattern — no new storage machinery.
- **The token-from-settings pattern exists**: `git_sync.resolve_token(domain)`
  reads `settings.github_token` / `settings.gitlab_token` per host. We mirror it
  for Jira.
- Data sources (`data_sources` table) still own the **endpoint** and any
  **non-secret** config (`auth_type`, `api_version`, `email`). No secret is
  stored there.

## Why `.env` (not encrypted-in-DB)

The earlier draft proposed encrypting the token inside `data_sources.config`
with redaction on read. Sourcing the secret from `.env` instead is simpler and
strictly safer:

- The token **never touches the database, the API, or any `GET` response** — no
  encrypt-at-rest, no redaction sentinel, no decrypt-in-router risk.
- Same trust model and operational story as the git tokens already in `.env`.
- Trade-off: the token is **not editable from the UI** — you set it in `.env`
  and restart the backend. (For a secret, that's arguably the right hygiene.)
  The UI still defines everything else (endpoint, auth type).

## `.env` loading caveat (must address)

`Settings.model_config` sets `env_prefix` but **not `env_file`**, so pydantic
does not read `.env` on its own:

- `make dev` (honcho, `Procfile.dev`) works because **honcho auto-loads `.env`**.
- `make backend` (bare `uvicorn`) does **not** load `.env` — existing tokens
  silently wouldn't be set there either.

**Recommended fix:** add `"env_file": ".env"` to `Settings.model_config` so the
backend reads `.env` directly regardless of launcher. Real environment variables
still take precedence over `.env` (correct for prod/containers). This also fixes
the latent gap for the existing git tokens under `make backend`.

## Design decisions (please review / refine)

### D1 — Which bits come from `.env` vs. the data source?

**Recommended split:**

| Lives in `.env` (secret) | Lives in the data source (UI-editable) |
|--------------------------|----------------------------------------|
| `OBSERVATORY_JIRA_TOKEN` | `endpoint` (Jira base URL) |
| `OBSERVATORY_JIRA_EMAIL` (Cloud basic auth only) | `config.auth_type` (`basic`/`bearer`) |
| | `config.api_version` (`2` or `3`) |

*Alternative:* put the endpoint in `.env` too and drop the Jira data-source row
entirely. Rejected as the default because the Intelligence Settings page is the
natural home for the endpoint and it keeps `query_jira`'s "is a Jira configured?"
check working the same way as MLflow/GitHub.

### D2 — Jira auth scheme

| `auth_type` | Used by | Header | Needs |
|-------------|---------|--------|-------|
| `bearer` | Jira **Server / Data Center** PAT | `Authorization: Bearer <JIRA_TOKEN>` | `JIRA_TOKEN` |
| `basic` | Jira **Cloud** | `Authorization: Basic base64(email:JIRA_TOKEN)` | `JIRA_EMAIL` + `JIRA_TOKEN` |

Red Hat's internal `issues.redhat.com` is Jira Server/DC → default `auth_type`
is likely `bearer`. Both supported; default chosen per your answer to D2 below.

### D3 — Behavior when the token is missing

If `OBSERVATORY_JIRA_TOKEN` is unset, keep today's **unauthenticated** request
(so an open Jira / emulator still works) and include a note in the tool result
that it ran unauthenticated. No hard failure.

## Approach

### Backend

1. **`src/backend/config.py`**
   - Add `jira_token: str = ""` and `jira_email: str = ""` to `Settings`.
   - Add `"env_file": ".env"` to `model_config` (see caveat above).

2. **`src/backend/chat/tools.py`** — authenticate `_handle_query_jira`:
   - Resolve endpoint + non-secret config via `_resolve_source(db, "jira")`.
   - Read `settings.jira_token` / `settings.jira_email`.
   - Build the header per D2 from `config.get("auth_type", "<default>")`.
   - Use `config.get("api_version", "2")` in the search path
     (`/rest/api/{version}/search`).
   - Honor `settings.ssl_verify` instead of the current hard-coded
     `verify=False` (fix while we're here — flag if you disagree).
   - If no token: unauthenticated request + a `"note": "unauthenticated"` field.

3. **`src/backend/chat/agent.py`** — one line noting `query_jira` now queries the
   configured, authenticated Jira instance.

### Frontend (`src/frontend/src/pages/IntelligenceSettings.tsx`)

- **No secret input needed** — the token isn't stored via the API.
- For a `jira` source, optionally surface friendly fields instead of raw JSON:
  an "Auth type" select (Bearer / Basic) writing `config.auth_type`, and an
  "API version" field. Endpoint uses the existing field.
- Add a hint under the form: *"The Jira API token is read from
  `OBSERVATORY_JIRA_TOKEN` in `.env` (and `OBSERVATORY_JIRA_EMAIL` for Cloud
  basic auth). Set it there and restart the backend."*

### Config docs

- Add `OBSERVATORY_JIRA_TOKEN=` and `OBSERVATORY_JIRA_EMAIL=` to `.env`
  (and to `.env.example` if one is created).

## Files to modify

| File | Change |
|------|--------|
| `src/backend/config.py` | add `jira_token`, `jira_email`; add `env_file` to `model_config` |
| `src/backend/chat/tools.py` | authenticate `_handle_query_jira` (header per `auth_type`, api_version, ssl_verify, unauth fallback) |
| `src/backend/chat/agent.py` | one line in system prompt |
| `src/frontend/src/pages/IntelligenceSettings.tsx` | jira auth-type/api-version fields + `.env` hint |
| `.env` (local) | add `OBSERVATORY_JIRA_TOKEN`, `OBSERVATORY_JIRA_EMAIL` |
| `src/tests/test_chat_*` (or new `test_jira_tool.py`) | header shape for basic/bearer; unauth fallback when no token; api_version path |

## Security invariants (must hold)

- The Jira token is read **only** from settings/`.env`; it is never written to
  the `data_sources` table, never returned by any router, never logged.
- If captured error text from Jira could echo credentials, scrub before
  returning (mirror `git_sync._scrub`).
- Outbound TLS verification follows `settings.ssl_verify`.

## Verification

1. `.venv/bin/ruff check src/backend` clean.
2. `PYTHONPATH=src .venv/bin/pytest src/tests/test_jira_tool.py -q` — bearer
   header when `auth_type=bearer`; basic `email:token` header when
   `auth_type=basic`; unauthenticated fallback when `jira_token` unset;
   `api_version` respected.
3. Confirm `.env` is picked up under both `make dev` and `make backend` after
   adding `env_file` (e.g. token present in `settings.jira_token`).
4. Live: set `OBSERVATORY_JIRA_TOKEN` in `.env`, restart, add/confirm a `jira`
   data source with the endpoint + `auth_type`, then ask the chat a Jira
   question and confirm authenticated results. Verify `GET /api/v1/data-sources`
   contains **no token**.
5. Frontend build passes (`cd src/frontend && npm run build`).

## Open questions for you

1. **D1**: keep the endpoint in the data source (recommended) or move the whole
   Jira connection into `.env`?
2. **D2**: target Jira **Cloud** (`basic`, needs email+token) or **Server/DC**
   (`bearer` PAT)? Sets the default `auth_type`.
3. OK to add `env_file=".env"` to `Settings` so `.env` works under `make backend`
   too (also fixes the existing git tokens there)?
4. OK to switch the Jira client from hard-coded `verify=False` to honoring
   `settings.ssl_verify`?
