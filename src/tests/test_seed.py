import json

import pytest

from backend.seed import load_seed_data, seed_database


@pytest.mark.asyncio
async def test_seed_populates_pipelines(tmp_db):
    """Verify that seeding creates the expected number of pipelines."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_seed_data()
    count = await seed_database(db, pipelines)

    assert count == 11

    cursor = await db.execute("SELECT COUNT(*) FROM pipelines")
    row = await cursor.fetchone()
    assert row[0] == 11


@pytest.mark.asyncio
async def test_seed_rfe_review_skills_and_jira(tmp_db):
    """Verify rfe-review pipeline has correct skills and jira contracts."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_seed_data()
    await seed_database(db, pipelines)

    # Check rfe-review pipeline exists
    cursor = await db.execute(
        "SELECT id, name, platform, owner FROM pipelines WHERE slug = 'rfe-review'"
    )
    row = await cursor.fetchone()
    assert row is not None
    pipeline_id = row[0]
    assert row[1] == "RFE Review Pipeline"
    assert row[2] == "gitlab"
    assert row[3] == "Jessica Forrester"

    # Check skills
    cursor = await db.execute(
        "SELECT repo_url, branch, purpose FROM pipeline_skills WHERE pipeline_id = ?",
        (pipeline_id,),
    )
    skills = await cursor.fetchall()
    assert len(skills) == 1
    assert skills[0][0] == "https://github.com/opendatahub-io/rfe-creator"
    assert skills[0][1] == "ci-prod"

    # Check jira contracts
    cursor = await db.execute(
        "SELECT project, labels_applied FROM pipeline_jira_contracts WHERE pipeline_id = ?",
        (pipeline_id,),
    )
    contracts = await cursor.fetchall()
    assert len(contracts) == 1
    assert contracts[0][0] == "RHAIRFE"
    labels = json.loads(contracts[0][1])
    assert "rfe-creator-autofix-rubric-pass" in labels
    assert "rfe-creator-feasibility-fail" in labels

    # Check artifact config
    cursor = await db.execute(
        "SELECT results_repo FROM pipeline_artifact_config WHERE pipeline_id = ?",
        (pipeline_id,),
    )
    artifact = await cursor.fetchone()
    assert artifact is not None
    assert artifact[0] == "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer-results"


@pytest.mark.asyncio
async def test_seed_autofix_triage_jira_contracts(tmp_db):
    """Verify autofix-triage pipeline has 4 Jira project contracts."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_seed_data()
    await seed_database(db, pipelines)

    cursor = await db.execute(
        "SELECT id FROM pipelines WHERE slug = 'autofix-triage'"
    )
    row = await cursor.fetchone()
    pipeline_id = row[0]

    cursor = await db.execute(
        "SELECT project FROM pipeline_jira_contracts WHERE pipeline_id = ? ORDER BY project",
        (pipeline_id,),
    )
    contracts = await cursor.fetchall()
    projects = [c[0] for c in contracts]
    assert projects == ["AIPCC", "INFERENG", "RHAIENG", "RHOAIENG"]


@pytest.mark.asyncio
async def test_seed_idempotent(tmp_db):
    """Running seed twice produces the same result."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_seed_data()

    # Seed first time
    await seed_database(db, pipelines)
    cursor = await db.execute("SELECT COUNT(*) FROM pipelines")
    count1 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_skills")
    skills_count1 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_jira_contracts")
    jira_count1 = (await cursor.fetchone())[0]

    # Seed second time
    await seed_database(db, pipelines)
    cursor = await db.execute("SELECT COUNT(*) FROM pipelines")
    count2 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_skills")
    skills_count2 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_jira_contracts")
    jira_count2 = (await cursor.fetchone())[0]

    assert count1 == count2 == 11
    assert skills_count1 == skills_count2
    assert jira_count1 == jira_count2
