#!/usr/bin/env python3
"""Collect raw pipeline data to ./var/.

Fetches three categories per pipeline:
  1. CI job artifact ZIPs    → ./var/artifacts/{slug}/ci-jobs/
  2. Data/results repos      → ./var/artifacts/{slug}/data-repo/
  3. Pipeline definitions    → ./var/definitions/{slug}/source-repo/
     + skill repos           → ./var/definitions/{slug}/skills/{name}/
     + shared lib repos      → ./var/definitions/{slug}/shared-libs/{name}/

Usage:
    python scripts/collect-artifacts.py                    # all pipelines, all types
    python scripts/collect-artifacts.py rfe-autofixer       # single pipeline
    python scripts/collect-artifacts.py --ci-only           # CI job artifacts only
    python scripts/collect-artifacts.py --data-repos-only   # data repos only
    python scripts/collect-artifacts.py --definitions-only  # source/skill/lib repos only

Reads config from org-pulse-config.json. Requires GITLAB_TOKEN and/or
GITLAB_TOKEN_INTERNAL in .env for the respective GitLab instances.
"""

import argparse
import io
import json
import logging
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote_plus, urlparse

try:
    import httpx
except ImportError:
    sys.exit("httpx is required: pip install httpx")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("collect-artifacts")

ROOT = Path(__file__).resolve().parent.parent
VAR = ROOT / "var" / "artifacts"
DEFS = ROOT / "var" / "definitions"
CONFIG_PATH = ROOT / "org-pulse-config.json"

# Load .env
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

SSL_VERIFY = os.environ.get("OBSERVATORY_SSL_VERIFY", "true").lower() != "false"

TOKENS: dict[str, str] = {}

def _load_tokens():
    """Load per-host GitLab tokens from .env or environment."""
    # GITLAB_TOKEN → gitlab.com
    t = os.environ.get("GITLAB_TOKEN", "")
    if t:
        TOKENS["gitlab.com"] = t
    # GITLAB_TOKEN_INTERNAL → gitlab.cee.redhat.com
    t = os.environ.get("GITLAB_TOKEN_INTERNAL", "")
    if t:
        TOKENS["gitlab.cee.redhat.com"] = t
    # Fallback: OBSERVATORY_GITLAB_TOKEN for any gitlab host
    t = os.environ.get("OBSERVATORY_GITLAB_TOKEN", "")
    if t:
        TOKENS.setdefault("gitlab.com", t)
    # OBSERVATORY_GITHUB_TOKEN
    t = os.environ.get("OBSERVATORY_GITHUB_TOKEN", "")
    if t:
        TOKENS["github.com"] = t


def get_token(repo_url: str) -> str | None:
    """Get the token for a repo URL based on its hostname."""
    parsed = urlparse(repo_url)
    return TOKENS.get(parsed.hostname or "", None)


def load_config() -> list[dict]:
    with open(CONFIG_PATH) as f:
        data = json.load(f)
    return data.get("pipelines", [])


def gitlab_api_base(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/v4"


def gitlab_project_path(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path


def git_clone_url(repo_url: str, token: str) -> str:
    """Insert token into HTTPS clone URL for authentication."""
    parsed = urlparse(repo_url)
    if "github.com" in (parsed.hostname or ""):
        return f"{parsed.scheme}://{token}@{parsed.netloc}{parsed.path}"
    return f"{parsed.scheme}://oauth2:{token}@{parsed.netloc}{parsed.path}"


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\[?[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def collect_ci_artifacts(pipeline: dict) -> None:
    """Download CI job artifact ZIPs and extract them."""
    slug = pipeline["slug"]
    repo = pipeline.get("repo", {})
    repo_url = repo.get("url", "")
    platform = repo.get("platform", "")

    if platform != "gitlab" or not repo_url:
        log.info("[%s] Skipping CI artifacts (platform=%s)", slug, platform)
        return

    token = get_token(repo_url)
    if not token:
        log.warning("[%s] No token for %s — skipping CI artifacts", slug, urlparse(repo_url).hostname)
        return

    base_url = gitlab_api_base(repo_url)
    project_path = quote_plus(gitlab_project_path(repo_url))
    headers = {"PRIVATE-TOKEN": token}

    ci_dir = VAR / slug / "ci-jobs"
    ci_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=60.0,
        verify=SSL_VERIFY,
        follow_redirects=True,
    ) as client:
        # Resolve project ID
        resp = client.get(f"/projects/{project_path}")
        if resp.status_code != 200:
            log.error("[%s] Failed to resolve project: HTTP %d", slug, resp.status_code)
            return
        project_id = resp.json()["id"]

        # Fetch recent pipelines (main branch only)
        resp = client.get(
            f"/projects/{project_id}/pipelines",
            params={"ref": "main", "per_page": 20, "order_by": "id", "sort": "desc"},
        )
        if resp.status_code != 200:
            log.error("[%s] Failed to fetch pipelines: HTTP %d", slug, resp.status_code)
            return

        pipelines_data = resp.json()
        log.info("[%s] Found %d pipelines on main", slug, len(pipelines_data))

        for p in pipelines_data:
            pid = p["id"]
            job_dir_base = ci_dir / str(pid)

            # Fetch jobs for this pipeline
            resp = client.get(f"/projects/{project_id}/pipelines/{pid}/jobs")
            if resp.status_code != 200:
                continue

            jobs = resp.json()
            for job in jobs:
                job_id = job["id"]
                job_name = job.get("name", "unknown")

                if not job.get("artifacts_file") and not job.get("artifacts"):
                    continue

                job_dir = job_dir_base / f"{job_id}-{job_name}"
                trace_path = job_dir / "job-trace.log"

                # Download artifact ZIP if not already collected
                if not job_dir.exists():
                    resp = client.get(f"/projects/{project_id}/jobs/{job_id}/artifacts")
                    if resp.status_code == 404:
                        continue
                    if resp.status_code != 200:
                        log.warning("[%s] Job %d artifacts: HTTP %d", slug, job_id, resp.status_code)
                        continue

                    try:
                        buf = io.BytesIO(resp.content)
                        with zipfile.ZipFile(buf, "r") as zf:
                            job_dir.mkdir(parents=True, exist_ok=True)
                            zf.extractall(job_dir)
                            count = len([n for n in zf.namelist() if not n.endswith("/")])
                            log.info("[%s] Extracted %d files from job %d (%s)", slug, count, job_id, job_name)
                    except zipfile.BadZipFile:
                        log.warning("[%s] Job %d: not a valid ZIP", slug, job_id)

                # Download job trace if missing
                if not trace_path.exists():
                    resp = client.get(f"/projects/{project_id}/jobs/{job_id}/trace")
                    if resp.status_code == 200 and resp.text:
                        job_dir.mkdir(parents=True, exist_ok=True)
                        trace_path.write_text(_strip_ansi(resp.text))
                        log.info("[%s] Saved job trace for job %d (%s) — %d lines", slug, job_id, job_name, resp.text.count("\n"))


def collect_data_repo(pipeline: dict) -> None:
    """Shallow clone or pull the data/results repo."""
    slug = pipeline["slug"]
    arts = pipeline.get("artifacts", {})
    results_repo = arts.get("resultsRepo", "")

    if not results_repo:
        return

    token = get_token(results_repo)
    if not token:
        log.warning("[%s] No token for %s — skipping data repo", slug, urlparse(results_repo).hostname)
        return

    repo_dir = VAR / slug / "data-repo"

    clone_url = git_clone_url(results_repo, token)
    env = dict(os.environ)
    if not SSL_VERIFY:
        env["GIT_SSL_NO_VERIFY"] = "1"

    if repo_dir.exists() and (repo_dir / ".git").exists():
        # Pull latest
        log.info("[%s] Pulling data repo %s", slug, results_repo)
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            log.warning("[%s] git pull failed: %s", slug, result.stderr.strip())
        else:
            log.info("[%s] Data repo updated", slug)
    else:
        # Shallow clone
        log.info("[%s] Cloning data repo %s", slug, results_repo)
        repo_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--depth=1", clone_url, str(repo_dir)],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            log.error("[%s] git clone failed: %s", slug, result.stderr.strip())
        else:
            file_count = sum(1 for _ in repo_dir.rglob("*") if _.is_file() and ".git" not in str(_))
            log.info("[%s] Cloned data repo (%d files)", slug, file_count)


def _clone_or_pull(repo_url: str, target_dir: Path, label: str) -> bool:
    """Shallow clone or pull a git repo. Returns True on success."""
    token = get_token(repo_url)
    clone_url = git_clone_url(repo_url, token) if token else repo_url
    env = dict(os.environ)
    if not SSL_VERIFY:
        env["GIT_SSL_NO_VERIFY"] = "1"

    if target_dir.exists() and (target_dir / ".git").exists():
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            log.warning("[%s] git pull failed: %s", label, result.stderr.strip()[:200])
            return False
        log.info("[%s] Updated %s", label, repo_url)
    else:
        target_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--depth=1", clone_url, str(target_dir)],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            log.error("[%s] git clone failed: %s", label, result.stderr.strip()[:200])
            return False
        log.info("[%s] Cloned %s", label, repo_url)
    return True


def collect_definitions(pipeline: dict) -> None:
    """Clone/pull the pipeline source repo, skill repos, and shared lib repos."""
    slug = pipeline["slug"]
    repo = pipeline.get("repo", {})
    repo_url = repo.get("url", "")

    if not repo_url:
        return

    defs_dir = DEFS / slug

    # Source repo
    _clone_or_pull(repo_url, defs_dir / "source-repo", f"{slug}/source")

    # Skill repos
    for skill in pipeline.get("skillRepos", []):
        skill_url = skill.get("repo", "")
        if not skill_url:
            continue
        name = urlparse(skill_url).path.strip("/").split("/")[-1]
        _clone_or_pull(skill_url, defs_dir / "skills" / name, f"{slug}/skills/{name}")

    # Shared lib repos
    for lib in pipeline.get("sharedLibs", []):
        lib_url = lib.get("repo", "")
        if not lib_url:
            continue
        name = urlparse(lib_url).path.strip("/").split("/")[-1]
        _clone_or_pull(lib_url, defs_dir / "shared-libs" / name, f"{slug}/shared-libs/{name}")


def main():
    parser = argparse.ArgumentParser(description="Collect pipeline data to ./var/")
    parser.add_argument("slugs", nargs="*", help="Pipeline slug(s) to collect (default: all)")
    parser.add_argument("--data-repos-only", action="store_true", help="Only collect data repos")
    parser.add_argument("--ci-only", action="store_true", help="Only collect CI job artifacts")
    parser.add_argument("--definitions-only", action="store_true", help="Only collect source/skill/lib repos")
    args = parser.parse_args()

    _load_tokens()

    if not TOKENS:
        log.error("No tokens found. Set GITLAB_TOKEN / GITLAB_TOKEN_INTERNAL in .env")
        sys.exit(1)

    for host, _ in TOKENS.items():
        log.info("Token loaded for %s", host)

    pipelines = load_config()

    if args.slugs:
        pipelines = [p for p in pipelines if p["slug"] in args.slugs]
        if not pipelines:
            log.error("No pipelines matched: %s", args.slugs)
            sys.exit(1)

    only = args.data_repos_only or args.ci_only or args.definitions_only

    log.info("Collecting data for %d pipeline(s) → %s", len(pipelines), ROOT / "var")

    for pipeline in pipelines:
        slug = pipeline["slug"]

        if not only or args.ci_only:
            try:
                collect_ci_artifacts(pipeline)
            except Exception:
                log.exception("[%s] CI artifact collection failed", slug)

        if not only or args.data_repos_only:
            try:
                collect_data_repo(pipeline)
            except Exception:
                log.exception("[%s] Data repo collection failed", slug)

        if not only or args.definitions_only:
            try:
                collect_definitions(pipeline)
            except Exception:
                log.exception("[%s] Definition collection failed", slug)

    log.info("Done.")


if __name__ == "__main__":
    main()
