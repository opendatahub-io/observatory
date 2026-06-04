import json
from pathlib import Path

import pytest

from backend.seed import load_org_pulse_config, seed_database


ORG_PULSE_PATH = Path(__file__).resolve().parent.parent.parent / "org-pulse-config.json"


@pytest.mark.asyncio
async def test_load_org_pulse_produces_six_pipelines():
    """Loading org-pulse-config.json should produce 6 pipelines."""
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    assert len(pipelines) == 6


@pytest.mark.asyncio
async def test_field_mapping(tmp_db):
    """Verify field mapping from org-pulse-config.json to our model."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    cursor = await db.execute(
        'SELECT slug, name, description, owner, repo_url, platform, '
        'cron, expected_interval_minutes, "group", display_order '
        'FROM pipelines WHERE slug = ?',
        ("rfe-autofixer",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "rfe-autofixer"
    assert row[1] == "RFE Review Pipeline"
    assert row[2] == "Discovers RHAIRFE Jira issues, scores against rubric, auto-revises descriptions"
    assert row[3] == "jforrester"
    assert row[4] == "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer"
    assert row[5] == "gitlab"
    assert row[6] == "0 11,23 * * *"
    assert row[7] == 720
    assert row[8] == "RFE"
    assert row[9] == 2


@pytest.mark.asyncio
async def test_group_and_display_order_stored(tmp_db):
    """Verify group and display_order are stored correctly for all pipelines."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    cursor = await db.execute(
        'SELECT slug, "group", display_order FROM pipelines ORDER BY display_order'
    )
    rows = await cursor.fetchall()

    result = {row[0]: (row[1], row[2]) for row in rows}
    assert result["rfe-assessor"] == ("RFE", 1)
    assert result["rfe-autofixer"] == ("RFE", 2)
    assert result["strat-pipeline"] == ("Strats", 3)
    assert result["epic-decomposer"] == ("Epics", 4)
    assert result["autofix"] == ("Bugs", 5)
    assert result["strat-security-reviews"] == ("Strats", 6)


@pytest.mark.asyncio
async def test_rfe_autofixer_has_jobs(tmp_db):
    """The rfe-autofixer pipeline has jobs=["autofix-rfe"] and group="RFE"."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    cursor = await db.execute(
        'SELECT jobs, "group" FROM pipelines WHERE slug = ?',
        ("rfe-autofixer",),
    )
    row = await cursor.fetchone()
    assert row is not None
    jobs = json.loads(row[0])
    assert jobs == ["autofix-rfe"]
    assert row[1] == "RFE"


@pytest.mark.asyncio
async def test_autofix_has_job_patterns(tmp_db):
    """The autofix pipeline has jobPatterns=["iterate-*", "triage-*", "autofix-*"]."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    cursor = await db.execute(
        "SELECT job_patterns FROM pipelines WHERE slug = ?",
        ("autofix",),
    )
    row = await cursor.fetchone()
    assert row is not None
    patterns = json.loads(row[0])
    assert patterns == ["iterate-*", "triage-*", "autofix-*"]


@pytest.mark.asyncio
async def test_pipelines_without_jobs_have_null(tmp_db):
    """Pipelines without jobs/jobPatterns should have NULL values."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    # strat-pipeline has empty jobs array and no jobPatterns
    cursor = await db.execute(
        "SELECT jobs, job_patterns FROM pipelines WHERE slug = ?",
        ("strat-pipeline",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None  # empty list -> NULL
    assert row[1] is None  # no jobPatterns -> NULL


@pytest.mark.asyncio
async def test_seed_idempotent_org_pulse(tmp_db):
    """Running seed twice with org-pulse-config produces the same result."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)

    # Seed first time
    await seed_database(db, pipelines)
    cursor = await db.execute("SELECT COUNT(*) FROM pipelines")
    count1 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_skills")
    skills1 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_jira_contracts")
    jira1 = (await cursor.fetchone())[0]

    # Seed second time
    await seed_database(db, pipelines)
    cursor = await db.execute("SELECT COUNT(*) FROM pipelines")
    count2 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_skills")
    skills2 = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM pipeline_jira_contracts")
    jira2 = (await cursor.fetchone())[0]

    assert count1 == count2 == 6
    assert skills1 == skills2
    assert jira1 == jira2


@pytest.mark.asyncio
async def test_jira_contract_mapping(tmp_db):
    """Verify jiraContract mapping for rfe-autofixer."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    cursor = await db.execute(
        "SELECT id FROM pipelines WHERE slug = ?", ("rfe-autofixer",)
    )
    pipeline_id = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT project, labels_applied FROM pipeline_jira_contracts WHERE pipeline_id = ?",
        (pipeline_id,),
    )
    contracts = await cursor.fetchall()
    assert len(contracts) == 1
    assert contracts[0][0] == "RHAIRFE"
    labels = json.loads(contracts[0][1])
    assert "rfe-creator-autofix-rubric-pass" in labels


@pytest.mark.asyncio
async def test_skills_mapping(tmp_db):
    """Verify skillRepos mapping for rfe-autofixer."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    cursor = await db.execute(
        "SELECT id FROM pipelines WHERE slug = ?", ("rfe-autofixer",)
    )
    pipeline_id = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT repo_url, branch, purpose FROM pipeline_skills WHERE pipeline_id = ?",
        (pipeline_id,),
    )
    skills = await cursor.fetchall()
    assert len(skills) == 1
    assert skills[0][0] == "https://github.com/opendatahub-io/rfe-creator"
    assert skills[0][1] == "ci-prod"


@pytest.mark.asyncio
async def test_artifact_config_mapping(tmp_db):
    """Verify artifacts mapping for rfe-autofixer."""
    from backend.database import get_db

    db = await get_db()
    pipelines = await load_org_pulse_config(ORG_PULSE_PATH)
    await seed_database(db, pipelines)

    cursor = await db.execute(
        "SELECT id FROM pipelines WHERE slug = ?", ("rfe-autofixer",)
    )
    pipeline_id = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT results_repo FROM pipeline_artifact_config WHERE pipeline_id = ?",
        (pipeline_id,),
    )
    artifact = await cursor.fetchone()
    assert artifact is not None
    assert artifact[0] == "https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer-results"
