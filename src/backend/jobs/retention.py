"""Background job: purge data older than retention thresholds."""

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

logger = logging.getLogger(__name__)

# Retention thresholds
TELEMETRY_SPANS_RETENTION_DAYS = 90
PROVENANCE_RETENTION_DAYS = 180  # run_commands, run_packages, run_containers

RUNTIME_DATA_TABLES = [
    "claim_evidence_records",
    "claim_regression_runs",
    "claim_stage_receipt_events",
    "claim_human_overrides",
    "claim_explanation_runs",
    "claim_verification_runs",
    "claim_coverage_elements",
    "claim_extraction_evaluations",
    "claim_occurrences",
    "claim_ambiguity_results",
    "claim_selection_results",
    "claim_source_units",
    "claim_extraction_runs",
    "claim_explanations",
    "claim_verdicts",
    "claim_jira_keys",
    "claim_sources",
    "claims",
    "sbom_vulnerabilities",
    "container_sboms",
    "trace_metadata",
    "trace_packages",
    "trace_events",
    "job_artifacts",
    "telemetry_dimensions",
    "otel_metric_points",
    "otel_log_records",
    "telemetry_summaries",
    "telemetry_spans",
    "run_commands",
    "run_packages",
    "run_containers",
    "mlflow_metrics",
    "mlflow_params",
    "mlflow_runs",
    "mlflow_experiments",
    "ci_job_scripts",
    "ci_job_variables",
    "ci_job_tags",
    "ci_jobs",
    "ci_includes",
    "collector_state",
    "chat_messages",
    "chat_conversations",
    "kb_articles",
    "kb_categories",
    "data_sources",
    "pipeline_runs",
]


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


async def wipe_runtime_data(db: aiosqlite.Connection) -> dict[str, int]:
    """Delete collected/runtime data while preserving configuration and credentials."""
    counts: dict[str, int] = {}

    for table in RUNTIME_DATA_TABLES:
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        counts[table] = (await cursor.fetchone())[0]
        await db.execute(f"DELETE FROM {table}")  # noqa: S608

    await db.commit()

    total = sum(counts.values())
    if total == 0:
        logger.info("Runtime data wipe: nothing to delete")
    else:
        logger.info("Runtime data wipe complete: %d total rows deleted", total)

    return counts
