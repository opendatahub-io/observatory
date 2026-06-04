"""Seed the observatory database from data/seed.json or org-pulse-config.json.

Usage:
    python -m backend.seed
"""

import asyncio
import json
from pathlib import Path

from backend.database import connect, disconnect, init_schema


_pkg_root = Path(__file__).resolve().parent.parent.parent
_candidates = [
    _pkg_root / "data" / "seed.json",
    Path("/app/data/seed.json"),
    Path("data/seed.json"),
]
SEED_FILE = next((p for p in _candidates if p.is_file()), _candidates[0])


async def load_seed_data(path: Path | None = None) -> list[dict]:
    """Load pipeline definitions from the seed JSON file."""
    p = path or SEED_FILE
    with open(p) as f:
        data = json.load(f)
    return data["pipelines"]


async def load_org_pulse_config(path: Path | None = None) -> list[dict]:
    """Load pipelines from org-pulse-config.json format."""
    p = path or (_pkg_root / "org-pulse-config.json")
    with open(p) as f:
        data = json.load(f)

    pipelines = []
    for entry in data.get("pipelines", []):
        repo = entry.get("repo", {})
        schedule = entry.get("schedule", {})

        pipeline = {
            "slug": entry["slug"],
            "name": entry["name"],
            "description": entry.get("description"),
            "owner": entry.get("owner"),
            "group": entry.get("group"),
            "display_order": entry.get("order"),
            "repo_url": repo.get("url", ""),
            "platform": repo.get("platform", ""),
            "cron": schedule.get("cron"),
            "expected_interval_minutes": schedule.get("expectedIntervalMinutes"),
            "timeout_minutes": schedule.get("timeoutMinutes"),
            "status": entry.get("status", "production"),
        }

        # jobs and job_patterns -- keep as lists
        jobs = entry.get("jobs")
        if jobs:
            pipeline["jobs"] = jobs
        job_patterns = entry.get("jobPatterns")
        if job_patterns:
            pipeline["job_patterns"] = job_patterns

        # images
        images = entry.get("images", [])
        if images:
            pipeline["images"] = [
                {"name": img.get("name"), "ref": img["ref"]} for img in images
            ]

        # skillRepos -> skills
        skill_repos = entry.get("skillRepos", [])
        if skill_repos:
            pipeline["skills"] = [
                {
                    "repo_url": s["repo"],
                    "branch": s.get("branch"),
                    "purpose": s.get("purpose"),
                }
                for s in skill_repos
            ]

        # sharedLibs -> shared_libs
        shared_libs = entry.get("sharedLibs", [])
        if shared_libs:
            pipeline["shared_libs"] = [
                {"repo_url": sl["repo"], "purpose": sl.get("purpose")}
                for sl in shared_libs
            ]

        # jiraContract -> jira_contracts
        jira_contract = entry.get("jiraContract")
        if jira_contract:
            pipeline["jira_contracts"] = [
                {
                    "project": project,
                    "labels_applied": jira_contract.get("labelsApplied", []),
                }
                for project in jira_contract.get("projects", [])
            ]

        # telemetry -> telemetry_config
        telemetry = entry.get("telemetry")
        if telemetry:
            pipeline["telemetry_config"] = {
                "collector_type": telemetry.get("otelCollector"),
                "endpoint": telemetry.get("otelEndpoint"),
                "summary_script": telemetry.get("summaryScript"),
                "status": telemetry.get("status", "active"),
            }

        # artifacts -> artifact_config
        artifacts = entry.get("artifacts")
        if artifacts:
            pipeline["artifact_config"] = {
                "results_repo": artifacts.get("resultsRepo"),
            }

        pipelines.append(pipeline)

    return pipelines


async def seed_database(db, pipelines: list[dict]) -> int:
    """Insert or replace pipelines and their related records.

    Returns the number of pipelines seeded.
    """
    for p in pipelines:
        # Serialize jobs/job_patterns as JSON strings for storage
        jobs_json = json.dumps(p["jobs"]) if p.get("jobs") else None
        job_patterns_json = json.dumps(p["job_patterns"]) if p.get("job_patterns") else None

        # Upsert the pipeline row
        await db.execute(
            """
            INSERT INTO pipelines
                (slug, name, description, owner, repo_url, platform,
                 cron, expected_interval_minutes, timeout_minutes, status,
                 "group", display_order, jobs, job_patterns,
                 updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                owner = excluded.owner,
                repo_url = excluded.repo_url,
                platform = excluded.platform,
                cron = excluded.cron,
                expected_interval_minutes = excluded.expected_interval_minutes,
                timeout_minutes = excluded.timeout_minutes,
                status = excluded.status,
                "group" = excluded."group",
                display_order = excluded.display_order,
                jobs = excluded.jobs,
                job_patterns = excluded.job_patterns,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                p["slug"],
                p["name"],
                p.get("description"),
                p.get("owner"),
                p["repo_url"],
                p["platform"],
                p.get("cron"),
                p.get("expected_interval_minutes"),
                p.get("timeout_minutes"),
                p.get("status", "production"),
                p.get("group"),
                p.get("display_order"),
                jobs_json,
                job_patterns_json,
            ),
        )

        # Get the pipeline id
        cursor = await db.execute(
            "SELECT id FROM pipelines WHERE slug = ?", (p["slug"],)
        )
        row = await cursor.fetchone()
        pipeline_id = row[0]

        # --- Images ---
        await db.execute(
            "DELETE FROM pipeline_images WHERE pipeline_id = ?", (pipeline_id,)
        )
        for img in p.get("images", []):
            await db.execute(
                """
                INSERT INTO pipeline_images (pipeline_id, name, ref)
                VALUES (?, ?, ?)
                """,
                (pipeline_id, img.get("name"), img["ref"]),
            )

        # --- Skills ---
        await db.execute(
            "DELETE FROM pipeline_skills WHERE pipeline_id = ?", (pipeline_id,)
        )
        for skill in p.get("skills", []):
            await db.execute(
                """
                INSERT INTO pipeline_skills (pipeline_id, repo_url, branch, purpose)
                VALUES (?, ?, ?, ?)
                """,
                (pipeline_id, skill["repo_url"], skill.get("branch"), skill.get("purpose")),
            )

        # --- Shared libs ---
        await db.execute(
            "DELETE FROM pipeline_shared_libs WHERE pipeline_id = ?", (pipeline_id,)
        )
        for lib in p.get("shared_libs", []):
            await db.execute(
                """
                INSERT INTO pipeline_shared_libs (pipeline_id, repo_url, purpose)
                VALUES (?, ?, ?)
                """,
                (pipeline_id, lib["repo_url"], lib.get("purpose")),
            )

        # --- Jira contracts ---
        await db.execute(
            "DELETE FROM pipeline_jira_contracts WHERE pipeline_id = ?", (pipeline_id,)
        )
        for contract in p.get("jira_contracts", []):
            labels_json = json.dumps(contract.get("labels_applied", []))
            await db.execute(
                """
                INSERT INTO pipeline_jira_contracts (pipeline_id, project, labels_applied)
                VALUES (?, ?, ?)
                """,
                (pipeline_id, contract["project"], labels_json),
            )

        # --- Telemetry config ---
        await db.execute(
            "DELETE FROM pipeline_telemetry_config WHERE pipeline_id = ?", (pipeline_id,)
        )
        telemetry = p.get("telemetry_config")
        if telemetry:
            await db.execute(
                """
                INSERT INTO pipeline_telemetry_config
                    (pipeline_id, collector_type, endpoint, summary_script, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    pipeline_id,
                    telemetry.get("collector_type"),
                    telemetry.get("endpoint"),
                    telemetry.get("summary_script"),
                    telemetry.get("status", "active"),
                ),
            )

        # --- Artifact config ---
        await db.execute(
            "DELETE FROM pipeline_artifact_config WHERE pipeline_id = ?", (pipeline_id,)
        )
        artifact = p.get("artifact_config")
        if artifact:
            await db.execute(
                """
                INSERT INTO pipeline_artifact_config (pipeline_id, results_repo, status)
                VALUES (?, ?, 'active')
                """,
                (pipeline_id, artifact.get("results_repo")),
            )

    await db.commit()
    return len(pipelines)


async def main() -> None:
    db = await connect()
    await init_schema(db)

    # Try org-pulse-config.json first, fall back to seed.json
    org_pulse_path = _pkg_root / "org-pulse-config.json"
    container_path = Path("/app/org-pulse-config.json")

    if org_pulse_path.is_file():
        pipelines = await load_org_pulse_config(org_pulse_path)
        print(f"Loading from {org_pulse_path}")
    elif container_path.is_file():
        pipelines = await load_org_pulse_config(container_path)
        print(f"Loading from {container_path}")
    else:
        pipelines = await load_seed_data()
        print(f"Loading from {SEED_FILE}")

    count = await seed_database(db, pipelines)
    print(f"Seeded {count} pipelines")
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
