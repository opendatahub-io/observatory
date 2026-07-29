# Plan: Git Repository Tooling for Chat Agent

**Status:** Pending — blocks Phase 8 (Chat & Knowledge Base) and enables deeper agent diagnostics

**Naming note:** this plan is filed as `git-repo-mcp-tooling.md` and referenced elsewhere as "MCP tools," matching the loose terminology already used in `phase-08-chat-and-knowledgebase.md`. There is no real Model Context Protocol server in this codebase — see "What already exists" below. The tools described here are added to the existing in-process `TOOL_DEFINITIONS`/`_TOOL_HANDLERS` dispatch table, not a new MCP transport.

## Goal

Extend the Observatory chat agent (Phase 8) with first-class access to git repositories — both pipeline repos and their associated skill repos. The agent must be able to inspect source code, job definitions, and skill implementations to answer contextual questions and help diagnose pipeline failures.

---

## Problem

The built-in chat agent in Observatory has access to:
- Pipeline artifacts, telemetry, job logs
- Claim verification history
- Knowledge base articles
- Filesystem browsing under a fixed allow-list (`browse_files`, `read_file`, `file_stats`, `search_files` in `src/backend/chat/tools.py`, scoped to `settings.chat_browse_roots`)

But it does **not** have access to:
- Git repos for the pipelines
- Skill implementations and documentation
- Job definitions and their evolution
- Source code that produces claims or runs jobs

In most cases when troubleshooting a pipeline or claim, the agent needs contextual clues from the underlying repos. For example:
- "Why did this skill claim X?" → Read the skill's source
- "What changed between these job runs?" → Diff the job definition
- "How does this pipeline work?" → Inspect the pipeline repo structure and CI config

Without repo access, the agent can only offer generic answers or ask the user to provide code snippets.

### What already exists (and why this plan is additive, not new infrastructure)

Observatory already tracks git repo URLs in three places, and already has a clone/pull mechanism for them:

- `pipelines.repo_url` (`src/backend/database.py`) — each pipeline's own source repo, `NOT NULL`.
- `pipeline_skills` (`pipeline_id, repo_url, branch, purpose`) — skill repos correlated to a pipeline. This is the "skill repo" concept the original ask referred to; it already exists as a child table, not a new object.
- `pipeline_shared_libs` (`pipeline_id, repo_url, purpose`) — shared library repos correlated to a pipeline.
- `scripts/collect-artifacts.py` already shallow-clones/pulls all three kinds of repo via `_clone_or_pull()` into `var/definitions/<slug>/{source-repo,skills/<name>,shared-libs/<name>}` (`collect_definitions()`), and separately clones each pipeline's results repo into `var/<slug>/data-repo/` (`collect_data_repo()`).
- `src/backend/chat/tools.py` already implements a `TOOL_DEFINITIONS` / `_TOOL_HANDLERS` / `execute_tool()` dispatch table — Anthropic tool-use function calling, wired into `src/backend/chat/agent.py`. Despite the "MCP" language in `phase-08-chat-and-knowledgebase.md`, there is no actual Model Context Protocol server or transport in this codebase; it's in-process function calling. This plan follows that existing pattern rather than introducing a real MCP server.
- `browse_files`/`read_file`/`file_stats`/`search_files` already implement path-validated file access via `_validate_path()` / `_get_allowed_roots()`, gated by `settings.chat_browse_roots` (default `/app/.context,/app/artifacts`). This is the mechanism new repo-read tools should extend, not duplicate.

**What's missing:** none of the above repo references are normalized into a single addressable entity, none of them are synced into a stable, queryable path the chat agent can browse, and the chat tool layer has no way to search across pipelines/skills/shared-libs by repo or read/grep their contents. This plan closes that gap by:

1. Introducing a `repositories` table that normalizes `pipelines.repo_url`, `pipeline_skills.repo_url`, and `pipeline_shared_libs.repo_url` into one entity, keyed by `(domain, owner, name)` so the same repo referenced from multiple places dedupes to one row.
2. Replacing the ad hoc `var/definitions/<slug>/...` layout with a stable `/checkouts/{domain}/{owner}/{name}` layout addressed by repository, not by pipeline slug — so a skill repo shared across five pipelines is cloned once, not five times.
3. Adding `repo_*` tools to the existing `TOOL_DEFINITIONS`/`_TOOL_HANDLERS` dispatch table, reusing `_validate_path()`/`_get_allowed_roots()` with `/checkouts` added to `chat_browse_roots`.

---

## Design

### 1. Repository Registry

Add a new table that normalizes existing repo references rather than sitting alongside them as an unrelated concept.

**Schema:**

```sql
CREATE TABLE repositories (
    id              TEXT PRIMARY KEY,
    domain          TEXT NOT NULL,                     -- github.com, gitlab.com, etc.
    owner           TEXT NOT NULL,                     -- user or organization
    name            TEXT NOT NULL,                     -- repo name
    kind            TEXT NOT NULL CHECK (kind IN ('pipeline_source', 'skill', 'shared_lib', 'results')),
    git_url         TEXT NOT NULL,                     -- full clone URL
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'archived')),
    default_branch  TEXT NOT NULL DEFAULT 'main',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (domain, owner, name)
);

-- Which pipelines reference which repositories, and in what capacity.
-- A single repository row (e.g. a shared skill repo) can be linked from many pipelines.
CREATE TABLE pipeline_repository_links (
    pipeline_id     TEXT NOT NULL REFERENCES pipelines(id),
    repository_id   TEXT NOT NULL REFERENCES repositories(id),
    relation        TEXT NOT NULL CHECK (relation IN ('source', 'skill', 'shared_lib', 'results')),
    purpose         TEXT,   -- carried over from pipeline_skills.purpose / pipeline_shared_libs.purpose
    branch          TEXT,   -- carried over from pipeline_skills.branch, if it overrides the repo default
    PRIMARY KEY (pipeline_id, repository_id, relation)
);
```

`kind`/`relation` mirror the distinction that already exists across `pipelines.repo_url` (source), `pipeline_skills` (skill), `pipeline_shared_libs` (shared_lib), and `pipeline_artifact_config.results_repo` (results) — this table doesn't introduce a new taxonomy, it gives the existing one a shared identity.

**Note on `results`.** The `results` value is included in the `CHECK` enums for forward compatibility, but this plan does **not** backfill, sync, or expose results repos — those remain owned by `collect_data_repo()` under `var/<slug>/data-repo/` (see Checkout Management). Either leave `results` reserved-but-unpopulated as written, or drop it from both enums until a later plan brings results repos into the registry; do not half-wire it (enum present but no migration/sync), which would imply support that isn't there.

**Migration:**

- Backfill `repositories` by parsing `git_url` from `pipelines.repo_url`, `pipeline_skills.repo_url`, and `pipeline_shared_libs.repo_url` into `(domain, owner, name)`, deduping on that triple.
- Backfill `pipeline_repository_links` from the corresponding rows (`relation='source'` for each `pipelines.repo_url`, `relation='skill'` for each `pipeline_skills` row, etc.), carrying over `purpose`/`branch`.
- Keep the existing `repo_url` columns on `pipelines`/`pipeline_skills`/`pipeline_shared_libs` as-is (do not drop them) — they remain the source of truth for pipeline CRUD and existing UI; `repositories` is a derived/synced index used for checkout management and chat tools. Reconciling which side is authoritative long-term is future work, out of scope here.
- On every pipeline/skill/shared-lib create-or-update, upsert the corresponding `repositories` + `pipeline_repository_links` rows (same parse-and-dedupe logic as the backfill).

### 2. Checkout Management

At runtime, maintain a `/checkouts` directory (bind-mounted PVC in k8s, plain host mount in dev) with all registered repos, organized by domain/owner/repo. This supersedes the per-pipeline `var/definitions/<slug>/{source-repo,skills/<name>,shared-libs/<name>}` layout in `scripts/collect-artifacts.py` — repos are now addressed by repository identity, so a skill repo shared by multiple pipelines is cloned once instead of once per pipeline.

**Layout:**
```
/checkouts/
  github.com/
    jctanner/
      observatory/
        .git/
        src/
        ci/
        README.md
    red-hat/
      redhat-2026_05_29_agentic_ci_observatory/
        .git/
        docs/
  gitlab.com/
    red-hat-internal/
      claim-extractors/
        .git/
        src/
```

**Sync Strategy:**
- On service startup, clone all active repos at their default branch (or cached ref).
- Periodically (hourly) `git fetch` + `git reset --hard` to default branch to keep repos current.
- On-demand refresh via API: `POST /api/v1/repositories/{id}/sync` for immediate fetch when debugging.
- Skip repos marked `inactive` or `archived` (already cloned but not refreshed).

**Where sync runs (and the resulting PVC access mode).** The clone/pull helpers this plan wants to reuse — `get_token()`, `git_clone_url()`, `_clone_or_pull()` — live in `scripts/collect-artifacts.py`, a standalone process invoked by `make collect-artifacts`, **not** in the backend service, and the backend has no existing import coupling to `scripts/`. Two options, and the plan must pick one because they have different infra costs:

- **(Recommended) Sync in the backend process.** Refactor the three helpers into a shared module importable by both the collector and the backend (e.g. `src/backend/git_sync.py`), and run the startup + hourly loop inside the backend. Because the same pod both writes and reads `/checkouts`, a single `ReadWriteOnce` PVC suffices. **Tokens are already available in the backend pod** — `k8s/base/deployment.yaml` mounts the `observatory-secrets` Secret via `envFrom`, and `config.py` already parses `OBSERVATORY_GITLAB_TOKEN`/`OBSERVATORY_GITHUB_TOKEN` into `settings.gitlab_token`/`settings.github_token`. The one gap: the collector also honors `GITLAB_TOKEN_INTERNAL` → `gitlab.cee.redhat.com`, which the backend config does **not** have. If any tracked repo lives on the internal GitLab host, add that token to `observatory-secrets` + a `settings.gitlab_token_internal` field and use a single per-host resolution path in the shared module.
- **Sync in the collector.** Keep clone logic in the collector process and have it write `/checkouts`; the backend only reads. This keeps clone/write concerns in the existing job, but now two different pods share `/checkouts`, forcing a `ReadWriteMany` PVC (not available on all storage classes) and introducing read-during-`reset --hard` races the backend must tolerate. Note this does *not* buy a token-isolation benefit — the backend already holds the git tokens today regardless.

Either way, `git_clone_url()` must **not** be reused as-is — see the token-leak note below.

**Credential handling (do not persist tokens into `.git/config`).** `git_clone_url()` embeds the token in the remote URL (`https://{token}@github.com/...`), which `git clone` writes verbatim into `.git/config`. Combined with `/checkouts` being on the chat allow-list, that hands the chat agent a live token for every git host. The reused helper must be replaced with a mechanism that keeps the token in **the sync subprocess's environment only** — never in argv, never in `.git/config`, never in what we log.

**Proposed mechanism.** `git_sync.py` shells out to `git` via `subprocess` with:

- A **tokenless clone/remote URL** — `https://oauth2@{host}/{owner}/{repo}.git` (username present, no secret). Because the URL carries no credential, nothing sensitive lands in `.git/config`, in `FETCH_HEAD`, or in any error message that echoes the URL.
- The token supplied through git's credential plumbing via env, using **one** of:
  - **`GIT_ASKPASS`** pointing at a small static helper (e.g. `scripts/git-askpass.sh` → `exec printenv OBSERVATORY_GIT_ASKPASS_TOKEN`); sync sets `OBSERVATORY_GIT_ASKPASS_TOKEN` to the resolved per-host token in the child process's `env=` for that one call. Mirrors the existing `oauth2:`/username scheme.
  - **`GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_0=http.extraHeader` / `GIT_CONFIG_VALUE_0=Authorization: …`** (git ≥2.31) — injects the auth header purely via env, applied only to that invocation and never persisted. No helper file needed.

**Why not the obvious alternatives:**

- **`git -c http.extraHeader=<token>` on the command line** — puts the token in argv, world-readable via `ps` / `/proc/<pid>/cmdline` inside the pod. Env injection avoids this; the command flag does not. Rejected.
- **Embed token in URL, then `git remote set-url` to strip it after clone** — the token is already written to `.git/config` during the clone window and survives an interrupted clone. This is cleanup, not prevention. Rejected.

**Anti-logging (the "never enters stdout/stderr" property):**

- Log only the tokenless URL; never format a token into any log line.
- Never set `GIT_TRACE_CURL` / `GIT_CURL_VERBOSE` in production (the former redacts `Authorization` by default, but don't rely on it).
- Capture subprocess stderr and scrub it before surfacing anywhere (defense-in-depth; with a tokenless URL there should be nothing to scrub).
- Ship a regression test asserting (a) no token in `.git/config` after clone and (b) no token in captured sync stdout/stderr.

**Confinement.** Authenticated git runs **only** in the sync path (`git_sync.py`, driven by startup/hourly loop and `POST /repositories/{id}/sync`). The chat/tool path never authenticates — `repo_read`/`repo_grep` read already-cloned files and `repo_history`/`repo_diff` run local `git log`/`git diff` with no network and no credential. So the token is structurally confined to one module's subprocess env and never reaches the chat agent's reach even in principle (the `.git/config` denylist in the Read side is the backstop for the disk vector).

**Disk footprint / eviction.** Every referenced repo is cloned and kept indefinitely — `DELETE` explicitly retains the checkout, and `archived` repos stay on disk. On a bounded PVC this grows without limit. Out of scope to fully solve here, but Phase A should at least (a) size the PVC deliberately, (b) shallow-clone (`--depth`) by default to bound per-repo size, and (c) file a follow-up for a GC/eviction policy for repos with no `active` `pipeline_repository_links`.

**Migration note:** `scripts/collect-artifacts.py`'s `collect_definitions()` (source/skill/shared-lib clones) becomes redundant once this sync runs and should be removed in Phase A to avoid the same repos being cloned twice under two different directory schemes. `collect_data_repo()` (results repos into `var/<slug>/data-repo/`) is a separate concern and is out of scope here.

### 3. Chat Tool Definitions

Add new tool definitions and handlers to the existing dispatch table in `src/backend/chat/tools.py` (`TOOL_DEFINITIONS` / `_TOOL_HANDLERS` / `execute_tool()`), following the same pattern as `query_pipelines`, `browse_files`, etc. — no new server or transport, just new entries in the existing table.

| Tool | Input | Output | Purpose |
|------|-------|--------|---------|
| `repo_search` | query, kind, limit | list of {repo_id, domain, owner, name, kind, path} | Find repos by name, owner, or kind |
| `repo_files` | repo_id, glob_pattern | list of {path, size, lines} | List files matching pattern in a repo |
| `repo_read` | repo_id, filepath | {path, content, encoding, lines} | Read file contents (truncated if >10KB) |
| `repo_grep` | repo_id, query, limit | list of {path, line_num, context, matches} | Grep for string/pattern across repo |
| `repo_history` | repo_id, filepath, limit | list of {commit, author, date, message} | Get git log for a file |
| `repo_diff` | repo_id, ref1, ref2 | {diff_format, stats, large_files_note} | Diff between refs (commits, branches) |
| `skill_definition` | repo_id | {yaml, parsed schema} | Read skill.yaml and parse skill contract |
| `job_definition` | repo_id, job_name | {yaml, provenance, last_run} | Read job definition with recent run metadata |

Tools return structured JSON, not raw content. File contents are truncated if >10KB; suggest pagination or specify line ranges.

`repo_read`/`repo_files`/`repo_grep` resolve `repo_id` to its `/checkouts/{domain}/{owner}/{name}` path and route through the existing `_validate_path()` against `_get_allowed_roots()` — `/checkouts` is added to `settings.chat_browse_roots` so the same path-**traversal** protections that already cover `browse_files`/`read_file` apply here.

**This is necessary but not sufficient.** `_validate_path()` (`tools.py:732`) only checks that the resolved path is under an allowed root; it does **not** filter file *content* or exclude dotfiles. Adding `/checkouts` to the allow-list therefore also exposes every repo's `.git/` directory to `browse_files`/`read_file`/`repo_read`/`repo_grep`. That is a live-credential leak, not a hypothetical one — see the `.git/config` token-exfiltration risk in [Security & Governance](#access-control). The repo tools (and, once `/checkouts` is on the allow-list, the pre-existing `browse_files`/`read_file`/`search_files` tools) therefore **do** need new logic: a `.git/`-and-secrets denylist applied on top of `_validate_path()`. Do not ship the `chat_browse_roots` change without it.

### 4. API Endpoints

Add REST endpoints for repository management. Most `repositories` rows come from the backfill/upsert described above (derived from pipeline/skill/shared-lib `repo_url` fields) — the POST endpoint exists for repos that aren't yet referenced by any pipeline (e.g. a skill repo being onboarded before its first pipeline link) and for operator overrides (status, branch).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/repositories` | Manually register a repo not yet derived from a pipeline/skill/shared-lib reference |
| GET | `/api/v1/repositories` | List all repos with status and checkout paths |
| GET | `/api/v1/repositories/{id}` | Get repo metadata, linked pipelines (via `pipeline_repository_links`), checkout path |
| PUT | `/api/v1/repositories/{id}` | Update repo config (description, status, default_branch) |
| POST | `/api/v1/repositories/{id}/sync` | Trigger immediate `git fetch` + `git reset` |
| DELETE | `/api/v1/repositories/{id}` | Deregister repo (stops syncing, keeps cached checkout) — blocked if `pipeline_repository_links` still references it |
| GET | `/api/v1/repositories/{domain}/{owner}/{name}` | Lookup by domain/owner/name |

**Example repo registration:**

```json
POST /api/v1/repositories
{
  "domain": "github.com",
  "owner": "jctanner",
  "name": "observatory",
  "kind": "pipeline_source",
  "git_url": "https://github.com/jctanner/observatory.git",
  "description": "Main Observatory pipeline repo"
}
```

Response:
```json
{
  "id": "repo_abc123",
  "domain": "github.com",
  "owner": "jctanner",
  "name": "observatory",
  "kind": "pipeline_source",
  "checkout_path": "/checkouts/github.com/jctanner/observatory",
  "status": "active",
  "created_at": "2026-07-28T..."
}
```

### 5. Integration with Phase 8 Chat

When the chat agent answers a question, it can now:

1. Search repositories by keyword or owner.
2. Read relevant source files or job definitions.
3. Explain findings with direct code references.
4. Suggest architectural context based on repo structure.

**Example agent flow:**

User: *"Why does the data-pipeline job fail with 'CLAIM_ASSURANCE_TIMEOUT'?"*

1. Agent calls `repo_search` with query "data-pipeline" to find matching pipeline repos
2. Agent calls `job_definition` to read the job spec from the repo
3. Agent calls `repo_grep` to find where CLAIM_ASSURANCE_TIMEOUT is set in the repo
4. Agent calls `repo_read` to inspect the skill source that raises the error
5. Agent synthesizes an answer with references to job definition, skill code, and commit history

---

## Implementation Phases

### Phase A: Repository Registry, Migration & Sync (3–4 days)

- Write **ADR-0028** (next free number) recording the load-bearing decisions here: `repositories` as a derived index rather than authoritative source; superseding `collect_definitions()`; where sync runs and the chosen PVC access mode; the no-token-in-`.git/config` rule. This repo records architectural decisions as ADRs (ADR-0001…0027) and the work-ledger convention requires it — don't leave these in the plan alone.
- Add `repositories` and `pipeline_repository_links` tables to `database.py`
- Write and run the backfill migration from `pipelines.repo_url` / `pipeline_skills.repo_url` / `pipeline_shared_libs.repo_url`, deduping on `(domain, owner, name)`
- Add upsert-on-write hooks so pipeline/skill/shared-lib CRUD keeps `repositories` + `pipeline_repository_links` in sync going forward
- Refactor `get_token()`/`git_clone_url()`/`_clone_or_pull()` out of `scripts/collect-artifacts.py` into a shared module (e.g. `src/backend/git_sync.py`) importable by both collector and backend — the backend has no coupling to `scripts/` today. Give it one per-host token-resolution path covering all four env vars the collector honors (backend already receives `OBSERVATORY_GITLAB_TOKEN`/`OBSERVATORY_GITHUB_TOKEN` via the `observatory-secrets` Secret; add `GITLAB_TOKEN_INTERNAL`/`gitlab.cee.redhat.com` to the Secret + config only if internal-host repos are tracked)
- Implement git sync logic (clone to `/checkouts/{domain}/{owner}/{name}`, fetch/reset loop) using the tokenless-URL + `GIT_ASKPASS`/`GIT_CONFIG_*` credential mechanism from Checkout Management → *Credential handling*; decide sync-in-backend vs sync-in-collector per the same section
- Remove `collect_definitions()`'s clone logic from `scripts/collect-artifacts.py` once sync is live, to avoid double-cloning the same repos under two layouts
- Provision the `/checkouts` PVC (access mode per the sync-location decision) and mount it into the reading/writing pod(s) (`k8s/base/deployment.yaml`, `pvc.yaml`) — this volume does not exist today; default to shallow clones to bound size
- Write tests for sync edge cases (auth, missing branches, large repos, dedupe collisions) plus the credential regression test (no token in `.git/config`; no token in captured sync stdout/stderr)

### Phase B: Chat Tools (2–3 days)

- Implement a `.git/`-and-secrets denylist layered on `_validate_path()` (applied to the new repo tools **and** the existing `browse_files`/`read_file`/`search_files`, which will now see `/checkouts`), with a test asserting `.git/config` is unreadable
- Add `/checkouts` to the default `settings.chat_browse_roots` — only together with the denylist above, never before
- Add `repo_search`, `repo_files`, `repo_read`, `repo_grep` to `TOOL_DEFINITIONS`/`_TOOL_HANDLERS` in `src/backend/chat/tools.py`, routing path-bearing tools through `_validate_path()` + denylist
- Implement `repo_history` and `repo_diff` handlers
- Add `skill_definition` and `job_definition` helpers
- Test tools against real Observatory-tracked repos once Phase A sync is live

### Phase C: Chat Integration (1 day)

- Register the new tools in `src/backend/chat/agent.py`'s tool set
- Update chat system prompt with repo context and access guidelines
- Test agent with sample questions requiring repo access

### Phase D: Operator UX (1 day)

- Add admin page to view/manage repos (most rows are auto-derived; manual registration and status/branch overrides are the primary actions)
- Show repo sync status, last fetch time, and checkout path
- Provide manual "Refresh" button

---

## Security & Governance

### Access Control

- Repository READ is available to the chat agent via the existing chat tool-call path (no direct filesystem access).
- Repository WRITE (`git push`, rebasing, branch mutation) is out of scope for the chat agent entirely in this plan — only operator-initiated sync (`fetch` + `reset --hard`) is implemented. If agent-driven rebase/write access is wanted later, it needs its own plan with explicit write-scoping, since it's a materially different risk profile than read-only tools.

**Credential-leak risk (must fix before shipping).** This is the highest-severity item in the plan, and it is created by the two things the plan otherwise recommends reusing:

1. `git_clone_url()` writes the auth token into each clone's `.git/config` remote URL.
2. Adding `/checkouts` to `chat_browse_roots` makes those `.git/config` files readable by the chat agent, because `_validate_path()` only blocks path traversal, not sensitive content.

Together, any user who can chat with the agent could ask it to read `/checkouts/<host>/<owner>/<repo>/.git/config` and receive a live push-capable token for that host. Both halves must be closed:

- **Sync side:** authenticate with the token in the sync subprocess's env only (tokenless URL + `GIT_ASKPASS` or `GIT_CONFIG_*` header injection), never persisting it into `.git/config`. Full mechanism and rejected alternatives in Checkout Management → *Credential handling*.
- **Read side:** apply a denylist on top of `_validate_path()` that excludes `.git/` and common secret files (`*.pem`, `*.key`, `.env`, `.npmrc`, `.netrc`, credential/token files) from `repo_read`/`repo_files`/`repo_grep` **and** from the pre-existing `browse_files`/`read_file`/`search_files`, since those now see `/checkouts` too.

- Beyond the denylist, tool results are further sanitized: PII and large binaries are filtered.

### Rate Limiting

- Tool calls are rate-limited to prevent abuse (e.g., grep floods).
- File reads are capped at 10KB; larger files require explicit pagination.
- Repo syncs are throttled to hourly + on-demand.

### Audit Trail

- Every repo sync is logged with timestamp and result.
- Agent tool calls are logged in chat message metadata (which agent, which tool, inputs, latency) — same mechanism already used for existing tools.
- Large or expensive queries are flagged for operator review.

---

## Success Criteria

- [ ] `repositories` table is backfilled from existing `pipelines`/`pipeline_skills`/`pipeline_shared_libs` repo references with no duplicate rows for the same `(domain, owner, name)`.
- [ ] Creating/editing a pipeline, skill, or shared-lib entry keeps `repositories`/`pipeline_repository_links` in sync automatically.
- [ ] Repos sync automatically to `/checkouts/{domain}/{owner}/{name}` hourly and on-demand, with `/checkouts` provisioned as a real PVC/mount.
- [ ] `scripts/collect-artifacts.py` no longer double-clones source/skill/shared-lib repos into `var/definitions/...`.
- [ ] Chat agent can query repos via the existing tool-call mechanism, reusing `_validate_path()` plus the new `.git`/secrets denylist.
- [ ] No token is ever written to `.git/config`, and `repo_read`/`browse_files` cannot read `.git/config` or common secret files (regression tests cover both).
- [ ] Agent answers to "Why did this job fail?" include relevant source context.
- [ ] Tool results respect privacy (no secrets in responses).
- [ ] Sync status is visible in Observatory UI with checkout paths.
- [ ] Performance: file reads / greps complete within 1s for typical repos.
- [ ] Repos from multiple domains (github.com, gitlab.com, etc.) coexist without collisions.

---

## Related Plans

- [[phase-08-chat-and-knowledgebase]] — Chat agent system prompt includes the new repo tools
- [[agentic-work-ledger]] — Agent work items can reference job/pipeline repos for context
- ADR-0028 (to be written in Phase A) — records the derived-index, sync-location, PVC, and credential-handling decisions made here
