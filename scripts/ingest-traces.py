#!/usr/bin/env python3
"""Ingest parsed trace events and OTEL event logs into the database.

Reads from two sources:
  1. ./var/traces/ — parsed job trace JSON (from parse-job-traces.py)
  2. ./var/artifacts/ — claude-otel.jsonl resourceLogs (structured OTEL events)

Usage:
    python scripts/ingest-traces.py                    # all
    python scripts/ingest-traces.py rfe-assessor       # single pipeline
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest-traces")

ROOT = Path(__file__).resolve().parent.parent
TRACES = ROOT / "var" / "traces"
ARTIFACTS = ROOT / "var" / "artifacts"
DB_PATH = ROOT / "data" / "observatory.db"


def resolve_run_id(db: sqlite3.Connection, pipeline_slug: str, pipeline_ext_id: str) -> int | None:
    row = db.execute("""
        SELECT r.id FROM pipeline_runs r
        JOIN pipelines p ON p.id = r.pipeline_id
        WHERE p.slug = ? AND r.external_id = ?
    """, (pipeline_slug, pipeline_ext_id)).fetchone()
    return row["id"] if row else None


def already_ingested(db: sqlite3.Connection, run_id: int, source: str) -> bool:
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM trace_events WHERE pipeline_run_id = ? AND source = ?",
        (run_id, source),
    ).fetchone()
    return row["cnt"] > 0


def ingest_job_trace(db: sqlite3.Connection, pipeline_slug: str, pipeline_ext_id: str, trace_path: Path) -> tuple[int, int, int]:
    """Ingest a parsed job trace JSON file. Returns (events, packages, metadata_keys)."""
    run_id = resolve_run_id(db, pipeline_slug, pipeline_ext_id)
    if not run_id:
        return 0, 0, 0

    if already_ingested(db, run_id, "job_trace"):
        return 0, 0, 0

    data = json.loads(trace_path.read_text())

    event_count = 0
    for e in data.get("events", []):
        content = e.get("text") or e.get("command") or e.get("prompt") or e.get("agent_id") or ""
        if e["type"] == "tool_call":
            content = json.dumps({"tool": e.get("tool"), "command": e.get("command")})
        elif e["type"] == "subagent_spawn":
            content = json.dumps({"agent_id": e.get("agent_id"), "prompt": e.get("prompt")})

        db.execute(
            "INSERT INTO trace_events (pipeline_run_id, source, event_type, timestamp, content, line_number) VALUES (?, 'job_trace', ?, ?, ?, ?)",
            (run_id, e["type"], e.get("timestamp"), content, e.get("line")),
        )
        event_count += 1

    pkg_count = 0
    for p in data.get("packages", []):
        db.execute(
            "INSERT INTO trace_packages (pipeline_run_id, manager, name, version, arch, repo) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, p["manager"], p["name"], p.get("version"), p.get("arch"), p.get("repo")),
        )
        pkg_count += 1

    meta_count = 0
    for key, value in data.get("metadata", {}).items():
        db.execute(
            "INSERT OR REPLACE INTO trace_metadata (pipeline_run_id, key, value) VALUES (?, ?, ?)",
            (run_id, key, str(value)),
        )
        meta_count += 1

    return event_count, pkg_count, meta_count


def ingest_otel_events(db: sqlite3.Connection, pipeline_slug: str, pipeline_ext_id: str, otel_path: Path) -> int:
    """Ingest OTEL resourceLogs from a claude-otel.jsonl file. Returns event count."""
    run_id = resolve_run_id(db, pipeline_slug, pipeline_ext_id)
    if not run_id:
        return 0

    if already_ingested(db, run_id, "otel"):
        return 0

    event_count = 0
    with open(otel_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            payload = d.get("payload", d)
            if "resourceLogs" not in payload:
                continue

            for rl in payload["resourceLogs"]:
                for sl in rl.get("scopeLogs", []):
                    for lr in sl.get("logRecords", []):
                        attrs = {
                            a["key"]: a.get("value", {}).get("stringValue", a.get("value", {}).get("intValue", ""))
                            for a in lr.get("attributes", [])
                        }
                        event_name = attrs.get("event.name", "unknown")
                        timestamp = attrs.get("event.timestamp")
                        sequence = attrs.get("event.sequence")

                        # Build content from key attributes
                        skip_keys = {"event.name", "event.timestamp", "event.sequence", "user.id", "session.id", "terminal.type"}
                        content_attrs = {k: v for k, v in attrs.items() if k not in skip_keys and v}
                        content = json.dumps(content_attrs) if content_attrs else ""

                        db.execute(
                            "INSERT INTO trace_events (pipeline_run_id, source, event_type, timestamp, content, line_number) VALUES (?, 'otel', ?, ?, ?, ?)",
                            (run_id, event_name, timestamp, content, sequence),
                        )
                        event_count += 1

    return event_count


def main():
    parser = argparse.ArgumentParser(description="Ingest trace events into the database")
    parser.add_argument("slugs", nargs="*", help="Pipeline slug(s) (default: all)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error("Database not found at %s", DB_PATH)
        sys.exit(1)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    total_events = 0
    total_packages = 0
    total_otel = 0

    # --- Job traces ---
    trace_files = []
    if args.slugs:
        for s in args.slugs:
            trace_files.extend((TRACES / s).rglob("*.events.json"))
    else:
        trace_files = list(TRACES.rglob("*.events.json"))

    log.info("Ingesting %d parsed job traces", len(trace_files))

    for trace_path in trace_files:
        parts = trace_path.relative_to(TRACES).parts
        if len(parts) < 3:
            continue
        pipeline_slug = parts[0]
        pipeline_ext_id = parts[1]

        events, pkgs, meta = ingest_job_trace(db, pipeline_slug, pipeline_ext_id, trace_path)
        total_events += events
        total_packages += pkgs

    db.commit()
    log.info("Job traces: %d events, %d packages ingested", total_events, total_packages)

    # --- OTEL event logs ---
    otel_files = []
    search_dir = ARTIFACTS
    if args.slugs:
        for s in args.slugs:
            otel_files.extend((ARTIFACTS / s).rglob("claude-otel.jsonl"))
    else:
        otel_files = list(ARTIFACTS.rglob("claude-otel.jsonl"))

    log.info("Ingesting OTEL events from %d files", len(otel_files))

    for otel_path in otel_files:
        parts = otel_path.relative_to(ARTIFACTS).parts
        if len(parts) < 4 or parts[1] != "ci-jobs":
            continue
        pipeline_slug = parts[0]
        pipeline_ext_id = parts[2]

        count = ingest_otel_events(db, pipeline_slug, pipeline_ext_id, otel_path)
        total_otel += count

    db.commit()
    db.close()

    log.info("Done. %d job trace events, %d packages, %d OTEL events ingested.", total_events, total_packages, total_otel)


if __name__ == "__main__":
    main()
