"""Background loop that keeps registered repositories checked out under
``settings.checkout_root``.

On each cycle, every ``active`` repository is cloned (shallow) if missing, or
``git fetch`` + ``git reset --hard`` to its default branch. Inactive/archived
repos are skipped (left on disk as-is). All git auth is handled by
``git_sync`` — tokens live only in the sync subprocess env, never on disk.
"""

import asyncio
import logging

import backend.config
from backend import git_sync
from backend.crud.repositories import record_sync_result
from backend.database import get_db

logger = logging.getLogger("backend.repo_sync")


async def sync_all_active(db) -> dict:
    """Sync every active repository once. Returns a {ok, failed} count summary."""
    cursor = await db.execute(
        "SELECT * FROM repositories WHERE status = 'active' ORDER BY id"
    )
    repos = await cursor.fetchall()
    if not repos:
        logger.info("No active repositories to sync")
        return {"ok": 0, "failed": 0}

    settings = backend.config.settings
    ok = 0
    failed = 0
    for row in repos:
        repo = dict(row)
        # subprocess git call is blocking — run off the event loop.
        result = await asyncio.to_thread(
            git_sync.sync_repository,
            repo["domain"],
            repo["owner"],
            repo["name"],
            settings.checkout_root,
            repo["default_branch"],
            settings.repo_sync_depth,
        )
        await record_sync_result(db, repo["id"], result["status"], result.get("error"))
        if result["status"] == "ok":
            ok += 1
        else:
            failed += 1

    logger.info("Repository sync cycle complete: %d ok, %d failed", ok, failed)
    return {"ok": ok, "failed": failed}


async def repo_sync_loop() -> None:
    """Run repository sync cycles on a schedule. Cancellable."""
    settings = backend.config.settings
    logger.info("Repository sync loop started")
    try:
        if not settings.repo_sync_on_startup:
            interval = settings.repo_sync_interval_minutes * 60
            await asyncio.sleep(interval)
        while True:
            try:
                db = await get_db()
                await sync_all_active(db)
            except Exception:
                logger.exception("Unhandled error in repository sync cycle")

            interval = settings.repo_sync_interval_minutes * 60
            logger.info("Sleeping %d seconds until next repository sync", interval)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Repository sync loop cancelled — shutting down")
        raise
