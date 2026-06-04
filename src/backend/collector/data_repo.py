"""Collect artifact files from GitLab data/results repositories."""

import logging
from urllib.parse import quote_plus, urlparse

import httpx

import backend.config
from backend.collector.artifacts import _guess_mime, MAX_FILE_SIZE

logger = logging.getLogger(__name__)


def _api_base(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    return f"{parsed.scheme}://{parsed.netloc}/api/v4"


def _project_path(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path


async def collect_data_repo(db, pipeline: dict) -> None:
    """Fetch files from a pipeline's data repo and store in job_artifacts."""
    results_repo = None
    pipeline_id = pipeline["id"]

    cursor = await db.execute(
        "SELECT results_repo FROM pipeline_artifact_config WHERE pipeline_id = ? AND status = 'active'",
        (pipeline_id,),
    )
    row = await cursor.fetchone()
    if row:
        results_repo = row[0]

    if not results_repo:
        return

    token = None
    try:
        from backend.crud.credentials import get_credential_for_pipeline
        token = await get_credential_for_pipeline(db, pipeline)
    except Exception:
        pass

    if not token:
        token = backend.config.settings.gitlab_token

    if not token:
        logger.debug("No token for data repo %s — skipping", results_repo)
        return

    base_url = _api_base(results_repo)
    project_path = _project_path(results_repo)
    encoded_path = quote_plus(project_path)
    headers = {"PRIVATE-TOKEN": token}

    async with httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=30.0,
        verify=backend.config.settings.ssl_verify,
        follow_redirects=True,
    ) as client:
        # Resolve default branch
        default_branch = "main"
        try:
            resp = await client.get(f"/projects/{encoded_path}")
            if resp.status_code == 200:
                project_info = resp.json()
                default_branch = project_info.get("default_branch", "main") or "main"
                logger.debug("Data repo %s default branch: %s", results_repo, default_branch)
        except httpx.HTTPError:
            pass

        # Check latest commit
        try:
            resp = await client.get(
                f"/projects/{encoded_path}/repository/commits",
                params={"per_page": 1, "ref_name": default_branch},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Failed to fetch commits for data repo %s: HTTP %d",
                    results_repo, resp.status_code,
                )
                return

            commits = resp.json()
            if not commits:
                return

            latest_sha = commits[0]["id"]
        except httpx.HTTPError as exc:
            logger.error("HTTP error checking data repo %s: %s", results_repo, exc)
            return

        # Check if we've already processed this commit
        cursor = await db.execute(
            "SELECT last_data_repo_sha FROM collector_state WHERE pipeline_id = ?",
            (pipeline_id,),
        )
        state = await cursor.fetchone()
        if state and state[0] == latest_sha:
            logger.debug("Data repo %s unchanged (sha=%s)", results_repo, latest_sha[:8])
            return

        # Get the most recent pipeline run to link artifacts to
        cursor = await db.execute(
            "SELECT id FROM pipeline_runs WHERE pipeline_id = ? ORDER BY started_at DESC LIMIT 1",
            (pipeline_id,),
        )
        run_row = await cursor.fetchone()
        if not run_row:
            logger.debug("No runs for pipeline %s — skipping data repo", pipeline.get("slug"))
            return
        run_id = run_row[0]

        # Clear old data repo artifacts for this run
        await db.execute(
            "DELETE FROM job_artifacts WHERE pipeline_run_id = ? AND source = 'data_repo'",
            (run_id,),
        )

        # Fetch repository tree (paginated)
        tree: list[dict] = []
        page = 1
        max_tree_pages = 10
        while page <= max_tree_pages:
            try:
                resp = await client.get(
                    f"/projects/{encoded_path}/repository/tree",
                    params={"recursive": "true", "per_page": 100, "page": page, "ref": default_branch},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Failed to fetch tree for data repo %s (page %d): HTTP %d",
                        results_repo, page, resp.status_code,
                    )
                    break

                page_data = resp.json()
                if not isinstance(page_data, list) or not page_data:
                    break

                tree.extend(page_data)
                if len(page_data) < 100:
                    break
                page += 1

            except httpx.HTTPError as exc:
                logger.error("HTTP error fetching tree for data repo %s: %s", results_repo, exc)
                break

        files = [entry for entry in tree if entry["type"] == "blob"]
        logger.info("Data repo %s: %d files in tree", results_repo, len(files))

        MAX_FILES = 500
        if len(files) > MAX_FILES:
            logger.warning(
                "Data repo %s has %d files — limiting to newest %d",
                results_repo, len(files), MAX_FILES,
            )
            files = files[-MAX_FILES:]

        stored = 0
        for entry in files:
            file_path = entry["path"]
            mime = _guess_mime(file_path)

            # Fetch file content
            try:
                resp = await client.get(
                    f"/projects/{encoded_path}/repository/files/{quote_plus(file_path)}/raw",
                    params={"ref": default_branch},
                )
                if resp.status_code != 200:
                    continue

                content = resp.content
                if len(content) > MAX_FILE_SIZE:
                    logger.debug("Skipping %s (%d bytes, exceeds limit)", file_path, len(content))
                    continue

                await db.execute(
                    """
                    INSERT INTO job_artifacts
                        (pipeline_run_id, source, source_ref, file_path, file_size, mime_type, content)
                    VALUES (?, 'data_repo', ?, ?, ?, ?, ?)
                    """,
                    (run_id, latest_sha[:12], file_path, len(content), mime, content),
                )
                stored += 1

            except httpx.HTTPError:
                continue

        await db.commit()

        # Update collector state with latest SHA
        await db.execute(
            "UPDATE collector_state SET last_data_repo_sha = ? WHERE pipeline_id = ?",
            (latest_sha, pipeline_id),
        )
        await db.commit()

        logger.info(
            "Stored %d data repo files for pipeline %s (sha=%s)",
            stored, pipeline.get("slug"), latest_sha[:8],
        )
