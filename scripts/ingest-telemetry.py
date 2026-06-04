#!/usr/bin/env python3
"""Parse claude-otel.jsonl files from ./var/artifacts/ and populate telemetry_summaries.

Walks ./var/artifacts/*/ci-jobs/*/claude-otel.jsonl, extracts the final
(max) value of each cumulative metric, and inserts into the database.

Usage:
    python scripts/ingest-telemetry.py              # all pipelines
    python scripts/ingest-telemetry.py rfe-assessor  # single pipeline
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
log = logging.getLogger("ingest-telemetry")

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "var" / "artifacts"
DB_PATH = ROOT / "data" / "observatory.db"


DIMENSION_KEYS = {
    "claude_code.cost.usage": ["model", "query_source"],
    "claude_code.token.usage": ["model", "type", "query_source"],
    "claude_code.lines_of_code.count": ["type"],
}


def parse_otel_jsonl(path: Path) -> tuple[dict, list[dict]]:
    """Extract final metric values and per-dimension breakdowns.

    Returns (aggregate_metrics, dimension_rows) where dimension_rows is a list
    of {"metric": ..., "key": ..., "value": ..., "amount": ...} dicts.
    """
    metrics: dict[str, float] = {}
    # dim_accum[(metric, dim_key, dim_value)] = max value seen
    dim_accum: dict[tuple[str, str, str], float] = {}

    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            payload = d.get("payload", d)
            if "resourceMetrics" not in payload:
                continue

            for rm in payload["resourceMetrics"]:
                for sm in rm.get("scopeMetrics", []):
                    for m in sm.get("metrics", []):
                        name = m["name"]
                        dp_list = (
                            m.get("sum", {}).get("dataPoints")
                            or m.get("gauge", {}).get("dataPoints")
                            or []
                        )
                        for dp in dp_list:
                            val = dp.get("asDouble", dp.get("asInt", 0))
                            if not isinstance(val, (int, float)):
                                continue

                            metrics[name] = max(metrics.get(name, 0), val)

                            attrs = {
                                a["key"]: a.get("value", {}).get("stringValue", "")
                                for a in dp.get("attributes", [])
                            }

                            wanted_keys = DIMENSION_KEYS.get(name, [])
                            for dk in wanted_keys:
                                dv = attrs.get(dk, "")
                                if dv:
                                    key = (name, dk, dv)
                                    dim_accum[key] = max(dim_accum.get(key, 0), val)

    dimensions = [
        {"metric": k[0], "key": k[1], "value": k[2], "amount": v}
        for k, v in dim_accum.items()
    ]

    return metrics, dimensions


def find_otel_files(slug: str | None = None) -> list[tuple[str, str, Path]]:
    """Find all claude-otel.jsonl files, returning (slug, pipeline_ext_id, path)."""
    results = []
    search_dir = ARTIFACTS / slug if slug else ARTIFACTS

    for otel_path in search_dir.rglob("claude-otel.jsonl"):
        parts = otel_path.relative_to(ARTIFACTS).parts
        if len(parts) < 4 or parts[1] != "ci-jobs":
            continue
        pipeline_slug = parts[0]
        pipeline_ext_id = parts[2]
        results.append((pipeline_slug, pipeline_ext_id, otel_path))

    return results


def main():
    parser = argparse.ArgumentParser(description="Ingest OTEL telemetry into the database")
    parser.add_argument("slugs", nargs="*", help="Pipeline slug(s) (default: all)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error("Database not found at %s", DB_PATH)
        sys.exit(1)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    slug_filter = args.slugs[0] if args.slugs else None
    otel_files = find_otel_files(slug_filter)

    if not otel_files:
        log.error("No claude-otel.jsonl files found")
        sys.exit(1)

    log.info("Found %d OTEL files to process", len(otel_files))

    inserted = 0
    skipped = 0

    for pipeline_slug, pipeline_ext_id, otel_path in otel_files:
        # Find pipeline_run_id
        row = db.execute("""
            SELECT r.id FROM pipeline_runs r
            JOIN pipelines p ON p.id = r.pipeline_id
            WHERE p.slug = ? AND r.external_id = ?
        """, (pipeline_slug, pipeline_ext_id)).fetchone()

        if not row:
            skipped += 1
            continue

        run_id = row["id"]

        # Check if already ingested
        existing = db.execute(
            "SELECT COUNT(*) as cnt FROM telemetry_summaries WHERE pipeline_run_id = ? AND source = 'artifact'",
            (run_id,),
        ).fetchone()

        if existing["cnt"] > 0:
            skipped += 1
            continue

        # Parse OTEL data
        metrics, dimensions = parse_otel_jsonl(otel_path)

        if not metrics:
            skipped += 1
            continue

        total_tokens = int(metrics.get("claude_code.token.usage", 0))
        cost_usd = metrics.get("claude_code.cost.usage", 0)
        duration_ms = int(metrics.get("claude_code.active_time.total", 0))

        if total_tokens == 0 and cost_usd == 0:
            skipped += 1
            continue

        db.execute("""
            INSERT INTO telemetry_summaries
                (pipeline_run_id, total_tokens, input_tokens, output_tokens, cost_usd, model, skill_name, duration_ms, source)
            VALUES (?, ?, 0, 0, ?, '', '', ?, 'artifact')
        """, (run_id, total_tokens, cost_usd, duration_ms))

        for dim in dimensions:
            db.execute("""
                INSERT INTO telemetry_dimensions
                    (pipeline_run_id, metric, dimension_key, dimension_value, value)
                VALUES (?, ?, ?, ?, ?)
            """, (run_id, dim["metric"], dim["key"], dim["value"], dim["amount"]))

        inserted += 1

    db.commit()
    db.close()

    log.info("Done. Inserted %d summaries, skipped %d (already exists or no data)", inserted, skipped)


if __name__ == "__main__":
    main()
