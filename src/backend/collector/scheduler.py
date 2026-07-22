"""Background collector loop that scrapes pipeline runs on a schedule."""

import asyncio
import logging
from datetime import datetime, timezone

import backend.config
from backend.collector.artifacts import download_and_process_artifacts
from backend.collector.base import get_collector
from backend.collector.crud import upsert_collector_state
from backend.collector.data_repo import collect_data_repo
from backend.database import get_db

logger = logging.getLogger(__name__)


async def run_collector_cycle(db) -> None:
    """Run one collection cycle across all registered pipelines."""
    logger.info("Collector cycle starting")

    cursor = await db.execute("SELECT * FROM pipelines")
    pipelines = await cursor.fetchall()

    if not pipelines:
        logger.info("No pipelines registered — nothing to collect")
        return

    for pipeline in pipelines:
        pipeline_dict = dict(pipeline)
        pipeline_id = pipeline_dict["id"]
        slug = pipeline_dict.get("slug", "?")
        platform = pipeline_dict.get("platform", "")

        try:
            collector = get_collector(platform)
            runs = await collector.collect_runs(db, pipeline_dict)

            # Upsert each run into pipeline_runs
            for run in runs:
                await db.execute(
                    """
                    INSERT INTO pipeline_runs
                        (pipeline_id, external_id, job, queued_at, started_at,
                         finished_at, duration_seconds, status, ref, web_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(pipeline_id, external_id) DO UPDATE SET
                        queued_at = COALESCE(excluded.queued_at, queued_at),
                        started_at = COALESCE(excluded.started_at, started_at),
                        finished_at = COALESCE(excluded.finished_at, finished_at),
                        duration_seconds = COALESCE(excluded.duration_seconds, duration_seconds),
                        status = excluded.status,
                        web_url = COALESCE(excluded.web_url, web_url)
                    """,
                    (
                        pipeline_id,
                        run["external_id"],
                        run.get("job"),
                        run.get("queued_at"),
                        run.get("started_at"),
                        run.get("finished_at"),
                        run.get("duration_seconds"),
                        run["status"],
                        run.get("ref"),
                        run.get("web_url"),
                    ),
                )
            await db.commit()

            # Determine the last external_id we inserted (if any)
            last_ext_id = runs[-1]["external_id"] if runs else None

            await upsert_collector_state(
                db,
                pipeline_id,
                last_collected_at=datetime.now(timezone.utc).isoformat(),
                last_run_external_id=last_ext_id,
                last_error=None,
                consecutive_failures=0,
            )

            logger.info(
                "Pipeline %s: collected %d run(s)",
                slug,
                len(runs),
            )

            # --- Artifact scraping for runs not yet processed ---
            artifact_errors = await _scrape_pending_artifacts(db, pipeline_dict)
            if artifact_errors:
                logger.warning(
                    "Pipeline %s: %d artifact scrape error(s): %s",
                    slug, len(artifact_errors), "; ".join(artifact_errors[:3]),
                )

            # --- Data repo collection ---
            try:
                await collect_data_repo(db, pipeline_dict)
            except Exception:
                logger.exception("Pipeline %s: data repo collection failed", slug)

        except Exception:
            logger.exception("Pipeline %s: collection failed", slug)

            # Fetch current consecutive_failures to increment
            state_cursor = await db.execute(
                "SELECT consecutive_failures FROM collector_state WHERE pipeline_id = ?",
                (pipeline_id,),
            )
            state_row = await state_cursor.fetchone()
            prev_failures = dict(state_row)["consecutive_failures"] if state_row else 0

            try:
                import traceback

                error_text = traceback.format_exc()
                await upsert_collector_state(
                    db,
                    pipeline_id,
                    last_collected_at=datetime.now(timezone.utc).isoformat(),
                    last_error=error_text,
                    consecutive_failures=prev_failures + 1,
                )
            except Exception:
                logger.exception("Failed to update collector_state for pipeline %s", slug)

    logger.info("Collector cycle complete")


_MAX_SCRAPE_ATTEMPTS = 5


async def _scrape_pending_artifacts(db, pipeline: dict) -> list[str]:
    """Download artifacts for runs that have not yet been scraped.

    Returns a list of error messages (empty on full success).
    """
    pipeline_id = pipeline["id"]
    slug = pipeline.get("slug", "?")

    cursor = await db.execute(
        """
        SELECT * FROM pipeline_runs
        WHERE pipeline_id = ? AND artifacts_scraped = FALSE
        """,
        (pipeline_id,),
    )
    pending_runs = await cursor.fetchall()

    if not pending_runs:
        return []

    logger.info(
        "Pipeline %s: %d run(s) pending artifact scraping",
        slug,
        len(pending_runs),
    )

    errors: list[str] = []
    for run_row in pending_runs:
        run = dict(run_row)
        run_ext = run.get("external_id", "?")
        attempts = run.get("artifact_scrape_attempts", 0) or 0

        if attempts >= _MAX_SCRAPE_ATTEMPTS:
            logger.warning(
                "Pipeline %s: run %s exceeded %d scrape attempts — marking as scraped",
                slug, run_ext, _MAX_SCRAPE_ATTEMPTS,
            )
            await db.execute(
                "UPDATE pipeline_runs SET artifacts_scraped = TRUE WHERE id = ?",
                (run["id"],),
            )
            await db.commit()
            continue

        try:
            result = await download_and_process_artifacts(db, pipeline, run)
            if result and result.get("error"):
                await db.execute(
                    "UPDATE pipeline_runs SET artifact_scrape_attempts = ? WHERE id = ?",
                    (attempts + 1, run["id"]),
                )
                await db.commit()
                errors.append(f"run {run_ext}: {result['error']}")
        except Exception:
            logger.exception(
                "Pipeline %s: artifact download failed for run %s",
                slug, run_ext,
            )
            await db.execute(
                "UPDATE pipeline_runs SET artifact_scrape_attempts = ? WHERE id = ?",
                (attempts + 1, run["id"]),
            )
            await db.commit()
            errors.append(f"run {run_ext}: unhandled exception")

    return errors


async def collector_loop() -> None:
    """Run collector cycles repeatedly, sleeping between them.

    Supports graceful cancellation via asyncio.CancelledError.
    """
    logger.info("Collector loop started")
    try:
        while True:
            try:
                db = await get_db()
                await run_collector_cycle(db)
            except Exception:
                logger.exception("Unhandled error in collector cycle")

            interval = backend.config.settings.collector_interval_minutes * 60
            logger.info("Sleeping %d seconds until next cycle", interval)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Collector loop cancelled — shutting down")
        raise
