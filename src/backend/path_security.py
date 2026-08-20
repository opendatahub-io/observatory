"""Shared path-security helpers for repository file access.

Extracted from chat/tools.py so the REST API and the chat agent share one
denylist. See ADR-0028 for the rationale: /checkouts is a browse root, but
.git internals and common secret files must never be served.
"""

from pathlib import Path

_DENIED_PATH_COMPONENTS = {".git"}
_DENIED_FILENAMES = {
    ".env", ".npmrc", ".netrc", ".pgpass", ".git-credentials",
    ".dockercfg", ".htpasswd", "credentials", "credentials.json",
}
_DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
_DENIED_NAME_SUBSTRINGS = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")


def is_denied_path(path: Path) -> bool:
    """True if a path is protected (VCS internals or a common secret file)."""
    if any(comp in _DENIED_PATH_COMPONENTS for comp in path.parts):
        return True
    lname = path.name.lower()
    if lname in _DENIED_FILENAMES:
        return True
    if lname.startswith(".env"):
        return True
    if any(lname.endswith(suf) for suf in _DENIED_SUFFIXES):
        return True
    if any(sub in lname for sub in _DENIED_NAME_SUBSTRINGS):
        return True
    return False


def validate_repo_path(checkout_root: Path, repo_dir: Path, raw: str) -> Path:
    """Resolve a user-supplied relative path within a repo checkout.

    Raises ValueError if the path escapes the repo directory or matches a
    denied pattern.
    """
    resolved = (repo_dir / raw).resolve()
    repo_resolved = repo_dir.resolve()
    if not (resolved == repo_resolved or repo_resolved in resolved.parents):
        raise ValueError(f"Path escapes repository root: {raw}")
    if is_denied_path(resolved):
        raise ValueError(
            f"Access denied: {raw} matches a protected path "
            "(.git internals or a secret file)"
        )
    return resolved
