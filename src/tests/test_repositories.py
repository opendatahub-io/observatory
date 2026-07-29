"""Tests for the repository registry, secure git sync, and the chat denylist.

Covers three security-critical properties from ADR-0028 and
docs/plans/git-repo-mcp-tooling.md:

  1. Registry backfill/upsert dedupes on (domain, owner, name) and parses
     nested GitLab subgroups + SCP-style URLs.
  2. The git token never lands in .git/config, argv, or captured output.
  3. The chat .git/secrets denylist blocks reading secrets even once
     /checkouts is a browse root.
"""

import os
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def repo_db(tmp_path):
    """Raw db connection with schema initialized."""
    db_path = tmp_path / "test_repos.db"
    os.environ["OBSERVATORY_DATABASE_PATH"] = str(db_path)

    import backend.config
    backend.config.settings = backend.config.Settings(database_path=db_path)

    import backend.database
    backend.database._db = None

    from backend.database import connect, disconnect, init_schema
    db = await connect()
    await init_schema(db)
    yield db
    await disconnect()
    backend.database._db = None


def _make_origin(tmp_path):
    """Create a local git repo with one commit and return its path."""
    origin = tmp_path / "origin"
    origin.mkdir()

    def run(*a):
        return subprocess.run(a, cwd=origin, check=True, capture_output=True)
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    (origin / "README.md").write_text("hello\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "init")
    return origin


# ---------------------------------------------------------------------------
# 1. Registry: parsing + dedupe
# ---------------------------------------------------------------------------

def test_parse_repo_url_variants():
    from backend.database import parse_repo_url

    assert parse_repo_url("https://github.com/acme/demo.git") == (
        "github.com", "acme", "demo")
    assert parse_repo_url("https://github.com/acme/demo") == (
        "github.com", "acme", "demo")
    # SCP-style
    assert parse_repo_url("git@gitlab.com:acme/demo.git") == (
        "gitlab.com", "acme", "demo")
    # Nested GitLab subgroup -> owner keeps the path
    assert parse_repo_url("https://gitlab.com/group/sub/skillrepo.git") == (
        "gitlab.com", "group/sub", "skillrepo")
    # Unparseable
    assert parse_repo_url("not-a-url") is None
    assert parse_repo_url("https://github.com/onlyowner") is None


@pytest.mark.asyncio
async def test_upsert_repository_dedupes_on_triple(repo_db):
    from backend.database import upsert_repository

    # Same repo via three URL forms -> one row.
    id1 = await upsert_repository(repo_db, "https://github.com/acme/demo.git", "pipeline_source")
    id2 = await upsert_repository(repo_db, "https://github.com/acme/demo", "skill")
    id3 = await upsert_repository(repo_db, "git@github.com:acme/demo.git", "shared_lib")
    await repo_db.commit()

    assert id1 == id2 == id3
    cursor = await repo_db.execute("SELECT COUNT(*) AS c FROM repositories")
    assert (await cursor.fetchone())["c"] == 1


@pytest.mark.asyncio
async def test_backfill_dedupes_shared_repo(repo_db):
    """A skill repo referenced by multiple pipelines yields one repo row and
    multiple links; re-running backfill is idempotent."""
    from backend.database import _backfill_repositories

    # Two pipelines share one skill repo.
    await repo_db.execute(
        "INSERT INTO pipelines (name, slug, platform, repo_url) VALUES (?,?,?,?)",
        ("P1", "p1", "github", "https://github.com/acme/app1"),
    )
    await repo_db.execute(
        "INSERT INTO pipelines (name, slug, platform, repo_url) VALUES (?,?,?,?)",
        ("P2", "p2", "github", "https://github.com/acme/app2"),
    )
    await repo_db.commit()
    for pid in (1, 2):
        await repo_db.execute(
            "INSERT INTO pipeline_skills (pipeline_id, repo_url, branch, purpose) "
            "VALUES (?,?,?,?)",
            (pid, "https://github.com/acme/shared-skill", "main", "linting"),
        )
    await repo_db.commit()

    await _backfill_repositories(repo_db)
    await _backfill_repositories(repo_db)  # idempotent

    # shared-skill appears once as a repo...
    cursor = await repo_db.execute(
        "SELECT COUNT(*) AS c FROM repositories WHERE name = 'shared-skill'")
    assert (await cursor.fetchone())["c"] == 1
    # ...but is linked from both pipelines.
    cursor = await repo_db.execute(
        "SELECT COUNT(*) AS c FROM pipeline_repository_links l "
        "JOIN repositories r ON r.id = l.repository_id WHERE r.name = 'shared-skill'")
    assert (await cursor.fetchone())["c"] == 2


@pytest.mark.asyncio
async def test_backfill_registers_artifact_results_repo(repo_db):
    """A pipeline's artifact/results repo is registered with kind='results' and
    linked with relation='results', so it appears on the Repositories page and
    is picked up by the sync loop."""
    from backend.database import _backfill_repositories

    await repo_db.execute(
        "INSERT INTO pipelines (name, slug, platform, repo_url) VALUES (?,?,?,?)",
        ("P1", "p1", "gitlab", "https://gitlab.com/acme/p1"),
    )
    await repo_db.commit()
    await repo_db.execute(
        "INSERT INTO pipeline_artifact_config (pipeline_id, results_repo, status) "
        "VALUES (?,?,?)",
        (1, "https://gitlab.com/acme/results-repo", "active"),
    )
    await repo_db.commit()

    await _backfill_repositories(repo_db)
    await _backfill_repositories(repo_db)  # idempotent

    cursor = await repo_db.execute(
        "SELECT kind FROM repositories WHERE name = 'results-repo'")
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "results"

    cursor = await repo_db.execute(
        "SELECT l.relation FROM pipeline_repository_links l "
        "JOIN repositories r ON r.id = l.repository_id WHERE r.name = 'results-repo'")
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["relation"] == "results"


# ---------------------------------------------------------------------------
# 2. Credential leak regression
# ---------------------------------------------------------------------------

def test_tokenless_url_has_no_token():
    from backend import git_sync

    url = git_sync.tokenless_clone_url("github.com", "acme", "demo")
    assert "SECRET" not in url
    assert url == "https://oauth2@github.com/acme/demo.git"


def test_auth_env_confines_token_to_env_values():
    from backend import git_sync

    token = "glpat-SECRET-TOKEN-VALUE"
    env = git_sync._auth_env("gitlab.com", token)

    # Collect every injected git config KEY/VALUE pair.
    count = int(env["GIT_CONFIG_COUNT"])
    pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(count)}

    # The token must never appear in a config KEY, and never verbatim in any
    # VALUE (the auth header is base64), and never in a URL.
    for key, value in pairs.items():
        assert token not in key
        assert token not in value
        assert "oauth2@" not in value  # header, not a credentialed URL

    # The auth header is scoped to the host's HTTPS URL.
    header_key = "http.https://gitlab.com/.extraHeader"
    assert header_key in pairs
    assert pairs[header_key].startswith("Authorization: Basic ")
    # Inherited credential helper / global askpass are neutralized.
    assert pairs["credential.helper"] == ""
    assert pairs["core.askpass"] == ""
    # Terminal prompt disabled so a missing token can't hang on a prompt.
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_auth_env_disables_gui_askpass():
    """A missing token must fail fast, never launch a GUI askpass (ksshaskpass)."""
    from backend import git_sync

    # Simulate a KDE desktop environment leaking askpass config into the process.
    env = git_sync.disable_credential_prompts({
        "SSH_ASKPASS": "/usr/bin/ksshaskpass",
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
    })

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == ""
    assert env["SSH_ASKPASS"] == ""  # ksshaskpass no longer reachable
    assert env["SSH_ASKPASS_REQUIRE"] == "never"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert "DISPLAY" not in env
    assert "WAYLAND_DISPLAY" not in env


def test_scrub_redacts_token():
    from backend import git_sync

    assert git_sync._scrub("fatal: bad glpat-SECRET here", "glpat-SECRET") == \
        "fatal: bad *** here"


@pytest.mark.asyncio
async def test_sync_never_writes_token_to_git_config(tmp_path, monkeypatch):
    """End-to-end: sync a real repo with a token configured, then assert the
    token is nowhere in .git/config and not in the returned output."""
    import backend.config
    from backend import git_sync

    origin = _make_origin(tmp_path)
    token = "glpat-SUPER-SECRET-DO-NOT-PERSIST"

    backend.config.settings = backend.config.Settings(github_token=token)
    # Point the clone at our local origin instead of a real https host so the
    # sync actually runs; the token is still injected into the subprocess env.
    monkeypatch.setattr(
        git_sync, "tokenless_clone_url",
        lambda domain, owner, name: f"file://{origin}",
    )

    checkout_root = tmp_path / "checkouts"
    result = git_sync.sync_repository(
        "github.com", "acme", "demo", checkout_root, default_branch="main")

    assert result["status"] == "ok", result
    checkout = checkout_root / "github.com" / "acme" / "demo"
    assert (checkout / "README.md").exists()

    # The token must NOT be anywhere in the persisted git config.
    config_text = (checkout / ".git" / "config").read_text()
    assert token not in config_text

    # ...nor in the returned result (path/error).
    assert token not in str(result)


# ---------------------------------------------------------------------------
# 3. Chat denylist
# ---------------------------------------------------------------------------

def test_is_denied_path_blocks_secrets():
    from pathlib import Path
    from backend.chat import tools

    denied = [
        "/checkouts/d/o/n/.git/config",
        "/checkouts/d/o/n/.env",
        "/checkouts/d/o/n/.env.local",
        "/checkouts/d/o/n/id_rsa",
        "/checkouts/d/o/n/.ssh/id_ed25519",
        "/checkouts/d/o/n/tls.pem",
        "/checkouts/d/o/n/server.key",
        "/checkouts/d/o/n/.npmrc",
        "/checkouts/d/o/n/.git-credentials",
    ]
    for p in denied:
        assert tools._is_denied_path(Path(p)), p

    allowed = [
        "/checkouts/d/o/n/main.py",
        "/checkouts/d/o/n/README.md",
        "/checkouts/d/o/n/src/app.js",
    ]
    for p in allowed:
        assert not tools._is_denied_path(Path(p)), p


def test_validate_path_raises_on_denied(tmp_path, monkeypatch):
    from backend.chat import tools

    monkeypatch.setattr(tools, "_get_allowed_roots", lambda: [tmp_path])
    # An allowed file resolves fine.
    ok = tmp_path / "main.py"
    ok.write_text("x")
    assert tools._validate_path(str(ok))
    # A .git/config under an allowed root is still rejected.
    with pytest.raises(ValueError):
        tools._validate_path(str(tmp_path / ".git" / "config"))
    with pytest.raises(ValueError):
        tools._validate_path(str(tmp_path / ".env"))


@pytest.mark.asyncio
async def test_repo_read_blocks_secret_files(repo_db, tmp_path, monkeypatch):
    """repo_read of a secret file returns an error, not its contents."""
    import backend.config
    from backend.chat import tools
    from backend.database import upsert_repository

    checkout_root = tmp_path / "checkouts"
    repo_dir = checkout_root / "github.com" / "acme" / "demo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "main.py").write_text("print('ok')\n")
    (repo_dir / ".env").write_text("TOKEN=leak\n")

    backend.config.settings = backend.config.Settings(
        checkout_root=checkout_root,
        chat_browse_roots=str(checkout_root),
    )
    monkeypatch.setattr(tools, "_get_allowed_roots", lambda: [checkout_root])

    rid = await upsert_repository(repo_db, "https://github.com/acme/demo", "pipeline_source")
    await repo_db.commit()

    # Normal file reads fine.
    ok = await tools._handle_repo_read(repo_db, {"repo_id": rid, "filepath": "main.py"})
    assert "content" in ok and "error" not in ok
    # Secret file is blocked.
    blocked = await tools._handle_repo_read(repo_db, {"repo_id": rid, "filepath": ".env"})
    assert "error" in blocked
    assert "leak" not in str(blocked)
