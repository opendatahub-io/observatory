"""Background job: generate SBOMs for container images using syft."""

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)


async def generate_missing_sboms(db: aiosqlite.Connection) -> int:
    """Find image digests in run_containers that don't have SBOMs, run syft, store results.

    Returns count of SBOMs generated.
    """
    if shutil.which("syft") is None:
        logger.warning("syft command not found on PATH; skipping SBOM generation")
        return 0

    # Find unique (image_digest, image_ref) pairs that don't yet have SBOMs.
    cursor = await db.execute(
        """
        SELECT DISTINCT rc.image_digest, rc.image_ref
        FROM run_containers rc
        WHERE rc.image_digest IS NOT NULL
          AND rc.image_digest != ''
          AND rc.image_digest NOT IN (SELECT image_digest FROM container_sboms)
        """
    )
    rows = await cursor.fetchall()

    if not rows:
        logger.info("No container images missing SBOMs")
        return 0

    generated = 0
    for row in rows:
        image_digest = row[0]
        image_ref = row[1]
        try:
            logger.info("Generating SBOM for %s (%s)", image_ref, image_digest)
            proc = await asyncio.create_subprocess_exec(
                "syft", image_ref, "-o", "spdx-json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(
                    "syft failed for %s (exit %d): %s",
                    image_ref, proc.returncode, stderr.decode(errors="replace"),
                )
                continue

            # Validate that the output is valid JSON
            sbom_text = stdout.decode(errors="replace")
            json.loads(sbom_text)  # raises ValueError if invalid

            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                """
                INSERT INTO container_sboms (image_digest, image_ref, format, sbom, generator, generated_at)
                VALUES (?, ?, 'spdx-json', ?, 'syft', ?)
                """,
                (image_digest, image_ref, sbom_text, now),
            )
            await db.commit()
            generated += 1
            logger.info("Stored SBOM for %s (%s)", image_ref, image_digest)

        except Exception:
            logger.exception("Error generating SBOM for %s (%s)", image_ref, image_digest)
            continue

    logger.info("SBOM generation complete: %d new SBOMs", generated)
    return generated
