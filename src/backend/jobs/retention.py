"""Background job: purge data older than retention thresholds."""

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

logger = logging.getLogger(__name__)

# Retention thresholds
TELEMETRY_SPANS_RETENTION_DAYS = 90
PROVENANCE_RETENTION_DAYS = 180  # run_commands, run_packages, run_containers


async def purge_old_data(db: aiosqlite.Connection) -> dict:
    """Purge data older than retention thresholds. Returns counts of deleted rows."""
    now = datetime.now(timezone.utc)
    span_cutoff = (now - timedelta(days=TELEMETRY_SPANS_RETENTION_DAYS)).isoformat()
    provenance_cutoff = (now - timedelta(days=PROVENANCE_RETENTION_DAYS)).isoformat()

    counts: dict[str, int] = {}

    # Delete telemetry_spans older than 90 days
    cursor = await db.execute(
        "DELETE FROM telemetry_spans WHERE created_at < ?",
        (span_cutoff,),
    )
    counts["telemetry_spans"] = cursor.rowcount

    cursor = await db.execute(
        "DELETE FROM otel_log_records WHERE created_at < ?",
        (span_cutoff,),
    )
    counts["otel_log_records"] = cursor.rowcount

    cursor = await db.execute(
        "DELETE FROM otel_metric_points WHERE created_at < ?",
        (span_cutoff,),
    )
    counts["otel_metric_points"] = cursor.rowcount

    # Delete run_commands older than 180 days
    cursor = await db.execute(
        "DELETE FROM run_commands WHERE created_at < ?",
        (provenance_cutoff,),
    )
    counts["run_commands"] = cursor.rowcount

    # Delete run_packages older than 180 days
    cursor = await db.execute(
        "DELETE FROM run_packages WHERE created_at < ?",
        (provenance_cutoff,),
    )
    counts["run_packages"] = cursor.rowcount

    # Delete run_containers older than 180 days
    cursor = await db.execute(
        "DELETE FROM run_containers WHERE created_at < ?",
        (provenance_cutoff,),
    )
    counts["run_containers"] = cursor.rowcount

    await db.commit()

    for table, count in counts.items():
        if count > 0:
            logger.info("Purged %d rows from %s", count, table)

    total = sum(counts.values())
    if total == 0:
        logger.info("Retention purge: nothing to delete")
    else:
        logger.info("Retention purge complete: %d total rows deleted", total)

    return counts
