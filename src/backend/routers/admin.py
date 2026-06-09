"""Admin API endpoints: database health, data retention purge, and seed."""

import logging
import os
from pathlib import Path

import aiosqlite
from fastapi import APIRouter, Depends

import backend.config
from backend.database import get_db
from backend.jobs.retention import purge_old_data
from backend.seed import load_org_pulse_config, load_seed_data, seed_database

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Tables to report counts for
_TABLES = [
    "pipelines",
    "pipeline_runs",
    "telemetry_spans",
    "telemetry_summaries",
    "run_commands",
    "run_packages",
    "run_containers",
    "container_sboms",
    "sbom_vulnerabilities",
]


@router.get("/db-health")
async def db_health(db: aiosqlite.Connection = Depends(get_db)):
    """Return database file size and row counts for key tables."""
    db_path = str(backend.config.settings.database_path)
    try:
        size = os.path.getsize(db_path)
    except OSError:
        size = 0

    table_counts: dict[str, int] = {}
    for table in _TABLES:
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        row = await cursor.fetchone()
        table_counts[table] = row[0]

    return {
        "database_size_bytes": size,
        "table_counts": table_counts,
    }


@router.post("/purge")
async def run_purge(db: aiosqlite.Connection = Depends(get_db)):
    """Run the data retention purge and return counts of deleted rows."""
    counts = await purge_old_data(db)
    return counts


@router.post("/seed")
async def run_seed(db: aiosqlite.Connection = Depends(get_db)):
    """Seed/update pipelines from org-pulse-config.json. Idempotent — updates existing, inserts new."""
    pkg_root = Path(__file__).resolve().parent.parent.parent.parent
    org_pulse_path = pkg_root / "org-pulse-config.json"
    container_path = Path("/app/org-pulse-config.json")

    if org_pulse_path.is_file():
        pipelines = await load_org_pulse_config(org_pulse_path)
        source = str(org_pulse_path)
    elif container_path.is_file():
        pipelines = await load_org_pulse_config(container_path)
        source = str(container_path)
    else:
        pipelines = await load_seed_data()
        source = "seed.json"

    count = await seed_database(db, pipelines)
    log.info("Seeded %d pipelines from %s", count, source)
    return {"seeded": count, "source": source}
