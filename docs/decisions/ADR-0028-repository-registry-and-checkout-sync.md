# ADR-0028: Repository Registry and Secure Checkout Sync

## Status

Accepted

## Context

Observatory tracks git repositories in three places — `pipelines.repo_url`
(source), `pipeline_skills.repo_url` (skill), and
`pipeline_shared_libs.repo_url` (shared lib) — plus
`pipeline_artifact_config.results_repo`. None of these are normalized into a
single addressable entity, and none are synced into a stable path the chat
agent can browse. The standalone `scripts/collect-artifacts.py` shallow-clones
source/skill/shared-lib repos into `var/definitions/<slug>/...`, keyed by
pipeline slug, so a skill repo shared by five pipelines is cloned five times.

To let the chat agent inspect repo source when diagnosing pipelines/claims (see
`docs/plans/git-repo-mcp-tooling.md`), we need a normalized registry, a stable
checkout layout, and chat tools to read it — without leaking git credentials.

## Decision

1. **Repository registry as a derived index.** Add a `repositories` table keyed
   by `UNIQUE (domain, owner, name)` and a `pipeline_repository_links` join
   table. It is **derived/synced**, not authoritative — the existing `repo_url`
   columns remain the source of truth for pipeline CRUD and existing UI. The
   registry is backfilled from those columns (deduping on the triple) and kept
   current by upsert-on-write hooks in the pipeline/skill/shared-lib CRUD.
   `id` is `INTEGER PRIMARY KEY` to match the relational core and the INTEGER FK
   to `pipelines.id`.

2. **Stable checkout layout `/checkouts/{domain}/{owner}/{name}`.** Repos are
   addressed by identity, so a shared skill repo is cloned once. This supersedes
   `collect_definitions()`'s per-slug `var/definitions/<slug>/...` layout, which
   is now a no-op to avoid double-cloning. `collect_data_repo()` (results repos)
   is unaffected and out of scope here.

3. **Sync runs in the backend process.** The clone/pull helpers were refactored
   out of `scripts/collect-artifacts.py` into `src/backend/git_sync.py`,
   importable by both collector and backend. A startup + hourly loop
   (`repo_sync_scheduler.py`) runs inside the backend. Because the same pod both
   writes and reads `/checkouts`, a single **ReadWriteOnce** PVC suffices (no
   ReadWriteMany requirement, no cross-pod read-during-reset races). Tokens are
   already present in the backend pod via the `observatory-secrets` Secret.

4. **No token in `.git/config` — ever.** The old `git_clone_url()` embedded the
   token in the remote URL, which `git` writes verbatim into `.git/config`.
   Combined with `/checkouts` on the chat allow-list, that would hand the chat
   agent a live push-capable token. The replacement (`git_sync.py`):
   - clones/fetches with a **tokenless URL** (`https://oauth2@{host}/...`);
   - injects auth via git's `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_N`/
     `GIT_CONFIG_VALUE_N` env plumbing (an `http.<url>.extraHeader:
     Authorization: Basic <...>` header scoped to the host), which applies only
     to the spawned process and is never persisted;
   - never puts the token in argv (rejects `git -c http.extraHeader=…`), never
     logs it, and scrubs captured stderr defensively.

5. **Read-side denylist (Phase B).** Adding `/checkouts` to `chat_browse_roots`
   is gated on a `.git/`-and-secrets denylist layered over `_validate_path()`,
   applied to both the new `repo_*` tools and the pre-existing
   `browse_files`/`read_file`/`search_files`. The allow-list change ships only
   with the denylist.

## Consequences

Positive:
- One addressable identity per repo; shared repos cloned once.
- Chat agent can read repo source through path-validated tools.
- Git tokens are structurally confined to the sync subprocess env — never on
  disk, argv, or logs. Regression tests assert both properties.
- ReadWriteOnce PVC works on all storage classes.

Negative:
- The registry duplicates repo references that also live on `repo_url` columns;
  reconciling long-term authority is deferred.
- Every referenced repo is cloned and kept indefinitely (DELETE retains the
  checkout; `archived` repos stay on disk). Growth is bounded only by shallow
  clones and deliberate PVC sizing; a GC/eviction policy for repos with no
  active links is a follow-up.
- `results` is reserved in the `kind`/`relation` enums but not synced or
  exposed by this work.
