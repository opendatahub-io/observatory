"""Parse run-manifest.json and populate provenance tables."""

from __future__ import annotations

import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def parse_run_manifest(
    db: aiosqlite.Connection,
    pipeline_run_id: int,
    data: dict,
) -> dict:
    """Parse a run-manifest.json and insert into provenance tables.

    Deletes any existing provenance rows for this run first so the
    operation is idempotent (safe for re-scraping).

    Returns ``{"commands": N, "packages": N, "containers": N}`` with
    the number of rows inserted in each category.
    """

    # Delete existing provenance data for idempotent re-scrape
    await db.execute(
        "DELETE FROM run_commands WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    )
    await db.execute(
        "DELETE FROM run_packages WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    )
    await db.execute(
        "DELETE FROM run_containers WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    )

    command_count = 0
    package_count = 0
    container_count = 0

    # -- Commands ----------------------------------------------------------
    for cmd in data.get("commands", []):
        await db.execute(
            """
            INSERT INTO run_commands
                (pipeline_run_id, step_order, command, exit_code, duration_ms, source)
            VALUES (?, ?, ?, ?, ?, 'manifest')
            """,
            (
                pipeline_run_id,
                cmd.get("step"),
                cmd.get("command"),
                cmd.get("exit_code"),
                cmd.get("duration_ms"),
            ),
        )
        command_count += 1

    # -- Packages ----------------------------------------------------------
    packages = data.get("packages", {})
    for manager, pkg_list in packages.items():
        for pkg in pkg_list:
            await db.execute(
                """
                INSERT INTO run_packages
                    (pipeline_run_id, manager, name, version, source)
                VALUES (?, ?, ?, ?, 'manifest')
                """,
                (
                    pipeline_run_id,
                    manager,
                    pkg.get("name"),
                    pkg.get("version"),
                ),
            )
            package_count += 1

    # -- Containers --------------------------------------------------------
    for ctr in data.get("containers", []):
        await db.execute(
            """
            INSERT INTO run_containers
                (pipeline_run_id, image_ref, image_digest, platform, source)
            VALUES (?, ?, ?, ?, 'manifest')
            """,
            (
                pipeline_run_id,
                ctr.get("image_ref"),
                ctr.get("image_digest"),
                ctr.get("platform"),
            ),
        )
        container_count += 1

    await db.commit()

    counts = {
        "commands": command_count,
        "packages": package_count,
        "containers": container_count,
    }
    logger.info(
        "Parsed run-manifest for pipeline_run_id=%d: %s",
        pipeline_run_id,
        counts,
    )
    return counts


async def extract_containers_from_ci(
    db: aiosqlite.Connection,
    pipeline_run_id: int,
    job_image: str | None,
) -> int:
    """Fallback: extract container info from CI job definition when no manifest.

    If *job_image* is provided (e.g. from the GitLab CI API job config),
    insert a single row into ``run_containers`` with ``source = 'api'``.

    Returns the number of rows inserted (0 or 1).
    """
    if not job_image:
        return 0

    await db.execute(
        """
        INSERT INTO run_containers
            (pipeline_run_id, image_ref, source)
        VALUES (?, ?, 'api')
        """,
        (pipeline_run_id, job_image),
    )
    await db.commit()
    logger.info(
        "Extracted fallback container image for pipeline_run_id=%d: %s",
        pipeline_run_id,
        job_image,
    )
    return 1
