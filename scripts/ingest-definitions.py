#!/usr/bin/env python3
"""Parse .gitlab-ci.yml files from ./var/definitions/ and insert into the database.

Usage:
    python scripts/ingest-definitions.py              # all pipelines
    python scripts/ingest-definitions.py rfe-autofixer # single pipeline
"""

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest-definitions")

ROOT = Path(__file__).resolve().parent.parent
DEFS = ROOT / "var" / "definitions"
DB_PATH = ROOT / "data" / "observatory.db"

RESERVED_KEYS = {
    "stages", "variables", "include", "default", "workflow",
    "image", "services", "cache", "before_script", "after_script",
}

SECRET_PATTERNS = re.compile(
    r"^\$.*(_TOKEN|_KEY|_SECRET|_PASSWORD|_CREDENTIALS|_CERT)", re.IGNORECASE
)


def load_ci_yaml(slug: str) -> dict | None:
    ci_path = DEFS / slug / "source-repo" / ".gitlab-ci.yml"
    if not ci_path.exists():
        log.warning("[%s] No .gitlab-ci.yml found", slug)
        return None
    with open(ci_path) as f:
        return yaml.safe_load(f)


def resolve_extends(job: dict, templates: dict) -> dict:
    """Merge a job with its extends template (single level, local only)."""
    extends = job.get("extends")
    if not extends:
        return job

    if isinstance(extends, str):
        extends = [extends]

    merged = {}
    for parent_name in extends:
        parent = templates.get(parent_name, {})
        if isinstance(parent, dict):
            for k, v in parent.items():
                if k not in merged:
                    merged[k] = v

    merged.update(job)
    return merged


def is_secret_value(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return bool(SECRET_PATTERNS.match(value))


def ingest_pipeline(db: sqlite3.Connection, slug: str) -> None:
    data = load_ci_yaml(slug)
    if not data:
        return

    cursor = db.execute("SELECT id FROM pipelines WHERE slug = ?", (slug,))
    row = cursor.fetchone()
    if not row:
        log.warning("[%s] Pipeline not found in DB — skipping", slug)
        return
    pipeline_id = row[0]

    # Clear existing definitions for this pipeline
    db.execute("DELETE FROM ci_includes WHERE pipeline_id = ?", (pipeline_id,))
    db.execute("""
        DELETE FROM ci_job_scripts WHERE job_id IN (SELECT id FROM ci_jobs WHERE pipeline_id = ?)
    """, (pipeline_id,))
    db.execute("""
        DELETE FROM ci_job_variables WHERE job_id IN (SELECT id FROM ci_jobs WHERE pipeline_id = ?)
    """, (pipeline_id,))
    db.execute("""
        DELETE FROM ci_job_tags WHERE job_id IN (SELECT id FROM ci_jobs WHERE pipeline_id = ?)
    """, (pipeline_id,))
    db.execute("DELETE FROM ci_jobs WHERE pipeline_id = ?", (pipeline_id,))

    # Collect templates (keys starting with .)
    templates = {}
    for key, val in data.items():
        if key.startswith(".") and isinstance(val, dict):
            templates[key] = val

    # Global variables
    global_vars = data.get("variables", {}) or {}

    # Parse includes
    includes = data.get("include", [])
    if isinstance(includes, dict):
        includes = [includes]
    elif not isinstance(includes, list):
        includes = []

    for inc in includes:
        if isinstance(inc, str):
            db.execute(
                "INSERT INTO ci_includes (pipeline_id, include_type, file) VALUES (?, 'local', ?)",
                (pipeline_id, inc),
            )
        elif isinstance(inc, dict):
            inc_type = "template" if "template" in inc else "project" if "project" in inc else "remote" if "remote" in inc else "local"
            db.execute(
                "INSERT INTO ci_includes (pipeline_id, include_type, project, file, ref) VALUES (?, ?, ?, ?, ?)",
                (
                    pipeline_id,
                    inc_type,
                    inc.get("project"),
                    inc.get("file") or inc.get("template") or inc.get("local") or inc.get("remote"),
                    inc.get("ref"),
                ),
            )

    # Parse jobs
    job_count = 0
    for key, val in data.items():
        if key in RESERVED_KEYS or key.startswith(".") or not isinstance(val, dict):
            continue

        # Skip trigger jobs (no real job definition)
        if "trigger" in val and "script" not in val:
            continue

        resolved = resolve_extends(val, templates)

        image = resolved.get("image")
        if isinstance(image, dict):
            image = image.get("name")

        stage = resolved.get("stage")
        timeout = resolved.get("timeout")
        extends_str = None
        raw_extends = val.get("extends")
        if isinstance(raw_extends, list):
            extends_str = ", ".join(raw_extends)
        elif isinstance(raw_extends, str):
            extends_str = raw_extends

        resource_group = resolved.get("resource_group")
        allow_failure = bool(resolved.get("allow_failure", False))

        cursor = db.execute(
            """INSERT INTO ci_jobs (pipeline_id, name, stage, image, timeout, extends, resource_group, allow_failure)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pipeline_id, key, stage, image, timeout, extends_str, resource_group, allow_failure),
        )
        job_id = cursor.lastrowid

        # Tags
        tags = resolved.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                db.execute("INSERT INTO ci_job_tags (job_id, tag) VALUES (?, ?)", (job_id, tag))

        # Variables (job-level merged with global)
        merged_vars = dict(global_vars)
        job_vars = resolved.get("variables", {}) or {}
        merged_vars.update(job_vars)

        for k, v in merged_vars.items():
            if isinstance(v, dict):
                v = v.get("value", str(v))
            v = str(v) if v is not None else ""
            if is_secret_value(v):
                v = "***"
                masked = True
            else:
                masked = False
            db.execute(
                "INSERT OR IGNORE INTO ci_job_variables (job_id, key, value, masked) VALUES (?, ?, ?, ?)",
                (job_id, k, v, masked),
            )

        # Scripts
        for phase in ("before_script", "script", "after_script"):
            commands = resolved.get(phase, [])
            if isinstance(commands, str):
                commands = [commands]
            if not isinstance(commands, list):
                continue
            for i, cmd in enumerate(commands):
                db.execute(
                    "INSERT INTO ci_job_scripts (job_id, phase, step_order, command) VALUES (?, ?, ?, ?)",
                    (job_id, phase, i, str(cmd)),
                )

        job_count += 1

    db.commit()
    log.info("[%s] Ingested %d jobs, %d includes", slug, job_count, len(includes))


def main():
    parser = argparse.ArgumentParser(description="Ingest CI definitions into the database")
    parser.add_argument("slugs", nargs="*", help="Pipeline slug(s) (default: all from ./var/definitions/)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error("Database not found at %s", DB_PATH)
        sys.exit(1)

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")

    if args.slugs:
        slugs = args.slugs
    else:
        slugs = sorted(
            d.name for d in DEFS.iterdir()
            if d.is_dir() and (d / "source-repo" / ".gitlab-ci.yml").exists()
        )

    if not slugs:
        log.error("No pipeline definitions found in %s", DEFS)
        sys.exit(1)

    log.info("Ingesting CI definitions for %d pipeline(s)", len(slugs))

    for slug in slugs:
        try:
            ingest_pipeline(db, slug)
        except Exception:
            log.exception("[%s] Ingestion failed", slug)

    db.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
