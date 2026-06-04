# ADR-0006: Database-Backed Platform Credential Management

## Status

Accepted

## Context

Observatory's collector uses `OBSERVATORY_GITLAB_TOKEN` and `OBSERVATORY_GITHUB_TOKEN` environment variables to authenticate against GitLab and GitHub APIs when scraping pipeline run data and artifacts. This has several problems:

1. **Single token per platform.** All GitLab pipelines share one PAT. If the token owner leaves the org or their account is deactivated, every GitLab pipeline goes dark simultaneously.
2. **No rotation without restart.** Changing a token requires redeploying the container or restarting the process.
3. **No visibility.** Operators can't see which token is in use, when it was last rotated, or whether it's close to expiring — without SSHing into the pod and inspecting the environment.
4. **No per-instance scoping.** Some GitLab repos are on `gitlab.com`, others on `gitlab.cee.redhat.com`. A single token can't authenticate to both. Currently there's no way to assign different tokens to different pipelines.

## Decision

Move platform credentials (GitLab PATs, GitHub PATs) into the database with CRUD management via the admin API and UI. Credentials are encrypted at rest using a server-side key.

### Data Model

```sql
CREATE TABLE platform_credentials (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                    -- human label ("gitlab.com PAT - jforrester")
    platform TEXT NOT NULL,                -- 'gitlab' | 'github'
    base_url TEXT NOT NULL,                -- 'https://gitlab.com' | 'https://gitlab.cee.redhat.com' | 'https://github.com'
    encrypted_token TEXT NOT NULL,          -- Fernet-encrypted token
    scopes TEXT NOT NULL DEFAULT '["*"]',  -- JSON array of pipeline slugs this credential covers
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,                  -- PAT expiration (if known)
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

### Encryption

Tokens are encrypted with Fernet (symmetric, from Python's `cryptography` package) using a key derived from `OBSERVATORY_CREDENTIAL_KEY` env var. If no key is set, fall back to a key derived from `OBSERVATORY_API_KEY` or reject credential creation with an error.

The encryption key is the one secret that must remain an env var — it protects everything else in the database.

### Credential Resolution

When the collector runs for a pipeline:
1. Look up credentials matching `pipeline.platform` AND whose `scopes` include the pipeline slug (or `["*"]`)
2. Prefer credentials whose `base_url` matches the pipeline's `repo_url` hostname
3. Decrypt the token for use in API calls
4. Update `last_used_at`
5. If no DB credential matches, fall back to the env var (`OBSERVATORY_GITLAB_TOKEN` / `OBSERVATORY_GITHUB_TOKEN`) for backwards compatibility

### API Endpoints

```
POST   /api/admin/credentials          Create credential (accepts plaintext token, stores encrypted)
GET    /api/admin/credentials          List credentials (no token values — name, platform, base_url, scopes, status)
PUT    /api/admin/credentials/{id}     Update (rotate token, change scopes)
DELETE /api/admin/credentials/{id}     Revoke (sets is_active=FALSE)
POST   /api/admin/credentials/{id}/test   Test connectivity (try to call the platform API)
```

### Admin UI

Add a "Platform Credentials" section to the Admin page:
- Table: Name, Platform, Base URL, Scopes, Last Used, Expires, Status, Actions
- Create form: name, platform dropdown, base URL, token (password field), scopes (pipeline multi-select), expiration
- Rotate: update token without changing the credential identity
- Test button: verifies the token works against the platform API

### Backwards Compatibility

Env vars (`OBSERVATORY_GITLAB_TOKEN`, `OBSERVATORY_GITHUB_TOKEN`) continue to work as fallback credentials with `["*"]` scope and the default platform base URL. Existing deployments don't break. The env vars are checked only when no matching DB credential exists.

## Consequences

Positive:
- Multiple tokens per platform (different GitLab instances, different token owners)
- Per-pipeline credential scoping (blast radius reduction)
- Token rotation without restart
- Visibility into credential health (last used, expiration tracking)
- Test-before-commit via the connectivity test endpoint

Negative:
- Requires `OBSERVATORY_CREDENTIAL_KEY` env var for encryption (one more secret to manage)
- Adds `cryptography` Python dependency
- More complex collector credential lookup path
