# Plan: Add `query_github` Chat Tool

## Context

The Observatory chat agent can query Jira and MLflow via live HTTP tools, but
has no way to interact with the GitHub emulator running in the cluster. Users
asking about repos, branches, PRs, commits, or file contents get no structured
answer. The GitHub emulator exposes the full GitHub REST API at `/api/v3/` and
all read endpoints work without authentication, so a read-only chat tool can
work with or without a configured token.

## Approach

Add a single `query_github` tool with an `action` enum, following the
`query_mlflow` pattern. This keeps tool count manageable while covering the
most useful read-only operations.

### Actions

| Action | Emulator endpoint | Key params |
|--------|-------------------|------------|
| `list_repos` | `GET /api/v3/users/{owner}/repos` | `owner` |
| `get_repo` | `GET /api/v3/repos/{owner}/{repo}` | `owner`, `repo` |
| `list_branches` | `GET /api/v3/repos/{owner}/{repo}/branches` | `owner`, `repo` |
| `list_commits` | `GET /api/v3/repos/{owner}/{repo}/commits` | `owner`, `repo`, `sha` (branch) |
| `list_pulls` | `GET /api/v3/repos/{owner}/{repo}/pulls` | `owner`, `repo`, `state` |
| `get_pull` | `GET /api/v3/repos/{owner}/{repo}/pulls/{number}` | `owner`, `repo`, `number` |
| `get_file` | `GET /api/v3/repos/{owner}/{repo}/contents/{path}` | `owner`, `repo`, `path`, `ref` |
| `search_code` | `GET /api/v3/search/code` | `query` |
| `search_issues` | `GET /api/v3/search/issues` | `query` |

### Auth handling

Use `_resolve_endpoint(db, "github_emulator")` to find the base URL. If the
data source's `config` JSON contains a `token` key, send
`Authorization: token <value>`. Otherwise make unauthenticated requests — the
emulator allows this for all reads. No fallback to env vars; the data source
table is the single source of truth for chat tools.

### Response shaping

Each action extracts a compact summary from the emulator's response — same
pattern as `query_jira`. Return only the fields useful for chat:

- **Repos**: `full_name`, `description`, `default_branch`, `private`, `html_url`
- **Branches**: `name`, `protected`
- **Commits**: `sha` (short), `message` (first line), `author`, `date`
- **PRs**: `number`, `title`, `state`, `user`, `head`/`base` refs, `merged`, `created_at`
- **File contents**: decoded `content` (base64 → text, capped at 10KB), `path`, `size`, `type`
- **Search**: `total_count`, compact `items`

### System prompt update

Add a brief note about GitHub tools in the existing system prompt, after the
Claim Assurance v2 section — just a sentence or two pointing the agent toward
the `query_github` tool for repo/branch/PR/code questions.

## Files to modify

1. **`src/backend/chat/tools.py`** — Add `query_github` tool definition and
   `_handle_query_github` handler with per-action dispatch. Register in
   `_TOOL_HANDLERS`.

2. **`src/backend/chat/agent.py`** — Add one line to `_BASE_SYSTEM_PROMPT`
   noting the GitHub tool availability.

3. **`src/tests/test_chat_claim_tools.py`** — Add a test confirming the tool
   definition exists in `TOOL_DEFINITIONS` and the handler is registered.
   (Full HTTP integration tests would need a running emulator; the tool
   definition and error-path tests are sufficient for unit coverage.)

## Verification

1. `make lint` passes
2. `uv run pytest src/tests/test_chat_claim_tools.py -v` passes
3. Frontend build passes (`cd src/frontend && npm run build`)
4. If emulator is running: register a `github_emulator` data source via the
   Intelligence Settings UI, then ask the chat "what repos exist?" and confirm
   it calls `query_github` with `action: list_repos`.
