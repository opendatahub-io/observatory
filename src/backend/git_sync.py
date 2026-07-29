"""Shared git checkout/sync helpers for the repository registry.

Security-critical module. The git auth token is confined to the environment of
the ``git`` subprocess for a single invocation and is:

  - never embedded in the remote URL (so it never lands in ``.git/config``),
  - never passed on the command line (so it never appears in ``ps`` /
    ``/proc/<pid>/cmdline``),
  - never formatted into a log line or surfaced in captured stdout/stderr.

Authentication is injected via git's ``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_N``
/ ``GIT_CONFIG_VALUE_N`` env plumbing (git >= 2.31), scoped to the target host's
URL, setting an ``http.<url>.extraHeader: Authorization: Basic <...>`` header.
These env-injected config entries apply only to the spawned process and are NOT
written to any repo's ``.git/config``.

This module is importable by both the backend service and the standalone
collector script; it replaces ``scripts/collect-artifacts.py``'s
``git_clone_url()`` (which embedded the token in the URL).
"""

import base64
import logging
import os
import subprocess
from pathlib import Path

import backend.config
from backend.database import parse_repo_url

log = logging.getLogger("backend.git_sync")

# Default clone depth. Shallow by default to bound per-repo disk footprint.
DEFAULT_DEPTH = 1


def resolve_token(domain: str) -> str | None:
    """Resolve the auth token for a git host from settings.

    Covers the same hosts the collector honors: github.com, gitlab.com, and the
    internal gitlab.cee.redhat.com (via ``settings.gitlab_token_internal`` when
    configured). Returns ``None`` when no token is configured for the host —
    the caller then clones anonymously (fine for public repos).
    """
    settings = backend.config.settings
    host = (domain or "").lower()
    if "github.com" in host:
        return settings.github_token or None
    if host == "gitlab.cee.redhat.com":
        return getattr(settings, "gitlab_token_internal", "") or None
    if "gitlab" in host:
        return settings.gitlab_token or None
    return None


def tokenless_clone_url(domain: str, owner: str, name: str) -> str:
    """Build a credential-free HTTPS clone URL.

    The ``oauth2@`` username carries no secret; it just mirrors the username
    half of the auth scheme so nothing sensitive is written to ``.git/config``.
    """
    return f"https://oauth2@{domain}/{owner}/{name}.git"


def _basic_auth_header(domain: str, token: str) -> str:
    """HTTP Basic auth header value for a host, matching the collector's scheme.

    GitHub: username = token (empty password). GitLab: username = ``oauth2``,
    password = token.
    """
    host = (domain or "").lower()
    if "github.com" in host:
        cred = f"{token}:"
    else:
        cred = f"oauth2:{token}"
    encoded = base64.b64encode(cred.encode()).decode()
    return f"Basic {encoded}"


def disable_credential_prompts(env: dict) -> dict:
    """Neutralize every interactive/GUI credential prompt for a git subprocess.

    ``GIT_TERMINAL_PROMPT=0`` alone only suppresses the *terminal* prompt; git
    (and ssh) will still launch a graphical askpass helper — e.g. KDE's
    ``ksshaskpass`` — inherited via ``SSH_ASKPASS``/``DISPLAY``. In a headless or
    background sync that dialog has no one to answer it, so the process hangs (or
    pops a stray window) instead of failing. We want auth-required repos to fail
    fast and be skipped.

    Emptying the askpass variables collapses git's prompt chain (GIT_ASKPASS →
    core.askPass → SSH_ASKPASS → terminal) down to the terminal prompt, which
    ``GIT_TERMINAL_PROMPT=0`` disables → git exits non-zero immediately. Removing
    ``DISPLAY`` and forcing ssh ``BatchMode`` close the GUI/ssh fallbacks too.
    Mutates and returns ``env``.
    """
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Empty (not unset) so these override anything inherited from the parent env.
    env["GIT_ASKPASS"] = ""
    env["SSH_ASKPASS"] = ""
    env["SSH_ASKPASS_REQUIRE"] = "never"
    # Any ssh transport (submodules, ssh remotes) must not prompt either.
    env["GIT_SSH_COMMAND"] = "ssh -oBatchMode=yes"
    # Without a display, git/ssh cannot launch a graphical askpass helper.
    for var in ("DISPLAY", "WAYLAND_DISPLAY"):
        env.pop(var, None)
    return env


def _auth_env(domain: str, token: str | None) -> dict:
    """Build the subprocess environment with token injected via GIT_CONFIG_*.

    The token only ever lives in the returned dict's values (passed as the
    child's ``env=``); it is never written to disk or the command line. Returns
    a fresh copy of ``os.environ`` with the auth config layered on top.
    """
    env = dict(os.environ)
    # Never prompt interactively or via a GUI askpass helper (ksshaskpass etc.).
    disable_credential_prompts(env)
    if not backend.config.settings.ssl_verify:
        env["GIT_SSL_NO_VERIFY"] = "1"

    # Base config applied to every invocation: disable any inherited credential
    # helper and any globally-configured askpass program (core.askPass in a
    # user's ~/.gitconfig would otherwise still launch a GUI prompt).
    config: list[tuple[str, str]] = [
        ("credential.helper", ""),
        ("core.askpass", ""),
    ]
    if token:
        header = _basic_auth_header(domain, token)
        # Scope the auth header to this host's HTTPS URL so it is never sent
        # anywhere else. GIT_CONFIG_* entries apply to this process only and are
        # not persisted into any .git/config.
        config.append((f"http.https://{domain}/.extraHeader", f"Authorization: {header}"))

    env["GIT_CONFIG_COUNT"] = str(len(config))
    for i, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


def _scrub(text: str, token: str | None) -> str:
    """Defensively redact a token from captured subprocess output."""
    if not text:
        return ""
    if token:
        text = text.replace(token, "***")
    return text


def checkout_path(checkout_root: Path, domain: str, owner: str, name: str) -> Path:
    """Resolve a repo's on-disk checkout path: <root>/<domain>/<owner>/<name>."""
    return Path(checkout_root) / domain / owner / name


def sync_repository(
    domain: str,
    owner: str,
    name: str,
    checkout_root: Path,
    default_branch: str = "main",
    depth: int = DEFAULT_DEPTH,
) -> dict:
    """Clone or update a single repository into the checkout tree.

    Clones (shallow) if not present; otherwise ``git fetch`` + ``git reset
    --hard`` to the default branch. Authentication is injected per-invocation
    via env only. Returns ``{"status": "ok"|"error", "path": str,
    "error": str|None}``. Never raises on git failure — errors are captured,
    scrubbed, and returned.
    """
    token = resolve_token(domain)
    target = checkout_path(checkout_root, domain, owner, name)
    url = tokenless_clone_url(domain, owner, name)
    env = _auth_env(domain, token)

    def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, env=env
        )

    try:
        if (target / ".git").exists():
            fetch = _run(
                ["git", "fetch", "--depth", str(depth), "origin", default_branch],
                cwd=target,
            )
            if fetch.returncode != 0:
                err = _scrub(fetch.stderr.strip()[:300], token)
                log.warning("[%s/%s/%s] fetch failed: %s", domain, owner, name, err)
                return {"status": "error", "path": str(target), "error": err}
            reset = _run(
                ["git", "reset", "--hard", f"origin/{default_branch}"], cwd=target
            )
            if reset.returncode != 0:
                err = _scrub(reset.stderr.strip()[:300], token)
                log.warning("[%s/%s/%s] reset failed: %s", domain, owner, name, err)
                return {"status": "error", "path": str(target), "error": err}
            log.info("[%s/%s/%s] updated (%s)", domain, owner, name, url)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            clone = _run(
                [
                    "git", "clone", "--depth", str(depth),
                    "--branch", default_branch, url, str(target),
                ]
            )
            if clone.returncode != 0:
                err = _scrub(clone.stderr.strip()[:300], token)
                log.error("[%s/%s/%s] clone failed: %s", domain, owner, name, err)
                return {"status": "error", "path": str(target), "error": err}
            log.info("[%s/%s/%s] cloned (%s)", domain, owner, name, url)
        return {"status": "ok", "path": str(target), "error": None}
    except OSError as exc:
        err = _scrub(str(exc), token)
        log.error("[%s/%s/%s] sync error: %s", domain, owner, name, err)
        return {"status": "error", "path": str(target), "error": err}


def sync_repo_url(
    git_url: str, checkout_root: Path, default_branch: str = "main", depth: int = DEFAULT_DEPTH
) -> dict:
    """Convenience wrapper: parse a git URL and sync it. Returns the sync result
    dict, or an error dict if the URL cannot be parsed."""
    parsed = parse_repo_url(git_url)
    if parsed is None:
        return {"status": "error", "path": None, "error": f"unparseable git url: {git_url}"}
    domain, owner, name = parsed
    return sync_repository(domain, owner, name, checkout_root, default_branch, depth)
