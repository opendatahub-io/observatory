#!/usr/bin/env python3
"""Ingest extracted claims from ./var/claims/ into the database.

Reads .claims.json files, deduplicates claims by content hash, extracts
Jira key references, and populates the claims, claim_sources, and
claim_jira_keys tables.

Usage:
    python scripts/ingest-claims.py                    # all claims
    python scripts/ingest-claims.py strat-pipeline     # single pipeline
"""

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest-claims")

ROOT = Path(__file__).resolve().parent.parent
CLAIMS_DIR = ROOT / "var" / "claims"
DB_PATH = ROOT / "data" / "observatory.db"

JIRA_KEY_PATTERN = re.compile(r"\b(RHAISTRAT|RHAIRFE|RHOAIENG|AIPCC|INFERENG|RHAIENG)-\d+\b")


def claim_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    normalized = normalized.rstrip(".,;:!?")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def extract_jira_keys(text: str) -> list[str]:
    return list(set(JIRA_KEY_PATTERN.findall(text) if False else [m.group(0) for m in JIRA_KEY_PATTERN.finditer(text)]))


def main():
    parser = argparse.ArgumentParser(description="Ingest claims into the database")
    parser.add_argument("slugs", nargs="*", help="Pipeline slug(s) (default: all)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error("Database not found at %s", DB_PATH)
        sys.exit(1)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    # Find claims files
    if args.slugs:
        claims_files = []
        for slug in args.slugs:
            claims_files.extend((CLAIMS_DIR / slug).rglob("*.claims.json"))
    else:
        claims_files = list(CLAIMS_DIR.rglob("*.claims.json"))

    if not claims_files:
        log.error("No .claims.json files found in %s", CLAIMS_DIR)
        sys.exit(1)

    log.info("Processing %d claims files", len(claims_files))

    total_claims = 0
    new_claims = 0
    total_sources = 0
    total_jira_links = 0

    for claims_file in claims_files:
        try:
            data = json.loads(claims_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping %s: %s", claims_file.name, exc)
            continue

        pipeline_slug = data.get("pipeline_slug", "unknown")
        source_file = data.get("source_file", str(claims_file.relative_to(CLAIMS_DIR)))

        for claim in data.get("claims", []):
            claim_text = claim.get("claim", "").strip()
            if not claim_text:
                continue

            total_claims += 1
            chash = claim_hash(claim_text)
            claim_type = claim.get("type")
            original_text = claim.get("original_text")

            # Upsert claim (deduplicate by hash)
            existing = db.execute("SELECT id FROM claims WHERE claim_hash = ?", (chash,)).fetchone()

            if existing:
                claim_id = existing["id"]
            else:
                cursor = db.execute(
                    "INSERT INTO claims (claim_text, claim_type, claim_hash) VALUES (?, ?, ?)",
                    (claim_text, claim_type, chash),
                )
                claim_id = cursor.lastrowid
                new_claims += 1

            # Add source link (skip if same source already linked)
            exists = db.execute(
                "SELECT id FROM claim_sources WHERE claim_id = ? AND source_file = ?",
                (claim_id, source_file),
            ).fetchone()

            if not exists:
                db.execute(
                    "INSERT INTO claim_sources (claim_id, pipeline_slug, source_file, original_text) VALUES (?, ?, ?, ?)",
                    (claim_id, pipeline_slug, source_file, original_text),
                )
                total_sources += 1

            # Extract Jira keys from claim text, original text, AND source file path
            jira_keys = extract_jira_keys(claim_text)
            if original_text:
                jira_keys.extend(extract_jira_keys(original_text))
            jira_keys.extend(extract_jira_keys(source_file))
            jira_keys = list(set(jira_keys))

            for jk in jira_keys:
                exists = db.execute(
                    "SELECT id FROM claim_jira_keys WHERE claim_id = ? AND jira_key = ?",
                    (claim_id, jk),
                ).fetchone()
                if not exists:
                    db.execute(
                        "INSERT INTO claim_jira_keys (claim_id, jira_key) VALUES (?, ?)",
                        (claim_id, jk),
                    )
                    total_jira_links += 1

    db.commit()
    db.close()

    log.info(
        "Done. %d total claims processed, %d new unique claims, %d source links, %d Jira key links",
        total_claims, new_claims, total_sources, total_jira_links,
    )


if __name__ == "__main__":
    main()
