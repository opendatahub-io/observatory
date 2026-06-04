"""Tests for the OTEL summary artifact parser."""

import pytest

from backend.database import get_db
from backend.collector.parsers.otel_summary import parse_otel_summary


FLAT_SUMMARY = {
    "total_tokens": 142000,
    "input_tokens": 120000,
    "output_tokens": 22000,
    "cost_usd": 4.23,
    "model": "claude-sonnet-4-20250514",
    "duration_ms": 3360000,
}

SKILL_SUMMARY = {
    "skills": [
        {
            "skill_name": "rfe.review",
            "total_tokens": 80000,
            "input_tokens": 70000,
            "output_tokens": 10000,
            "cost_usd": 2.50,
            "model": "claude-sonnet-4-20250514",
            "duration_ms": 1800000,
        },
        {
            "skill_name": "rfe.split",
            "total_tokens": 62000,
            "input_tokens": 50000,
            "output_tokens": 12000,
            "cost_usd": 1.73,
            "model": "claude-sonnet-4-20250514",
            "duration_ms": 1560000,
        },
    ]
}


async def _seed_pipeline_run(db):
    """Insert a minimal pipeline and pipeline_run, return pipeline_run id."""
    await db.execute(
        "INSERT INTO pipelines (slug, name, repo_url, platform) VALUES (?, ?, ?, ?)",
        ("test-pipe", "Test", "https://example.com/repo", "github"),
    )
    cursor = await db.execute(
        "INSERT INTO pipeline_runs (pipeline_id, external_id, status) VALUES (1, 'run-1', 'success')",
    )
    await db.commit()
    return cursor.lastrowid


async def _count_summaries(db, pipeline_run_id):
    cursor = await db.execute(
        "SELECT COUNT(*) FROM telemetry_summaries WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    )
    row = await cursor.fetchone()
    return row[0]


async def _get_summaries(db, pipeline_run_id):
    cursor = await db.execute(
        "SELECT * FROM telemetry_summaries WHERE pipeline_run_id = ? ORDER BY id",
        (pipeline_run_id,),
    )
    return await cursor.fetchall()


# ── Flat format ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flat_format_inserts_one_row(tmp_db):
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    inserted = await parse_otel_summary(db, run_id, FLAT_SUMMARY)

    assert inserted == 1
    assert await _count_summaries(db, run_id) == 1

    rows = await _get_summaries(db, run_id)
    row = rows[0]
    assert row["total_tokens"] == 142000
    assert row["input_tokens"] == 120000
    assert row["output_tokens"] == 22000
    assert row["cost_usd"] == pytest.approx(4.23)
    assert row["model"] == "claude-sonnet-4-20250514"
    assert row["duration_ms"] == 3360000
    assert row["source"] == "artifact"
    assert row["skill_name"] is None


# ── Per-skill format ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_format_inserts_per_skill(tmp_db):
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    inserted = await parse_otel_summary(db, run_id, SKILL_SUMMARY)

    assert inserted == 2
    assert await _count_summaries(db, run_id) == 2

    rows = await _get_summaries(db, run_id)
    assert rows[0]["skill_name"] == "rfe.review"
    assert rows[0]["total_tokens"] == 80000
    assert rows[1]["skill_name"] == "rfe.split"
    assert rows[1]["total_tokens"] == 62000


# ── Missing / partial fields ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_flat_data(tmp_db):
    """Only some fields present -- should insert without error."""
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    partial = {"total_tokens": 5000, "model": "gpt-4o"}
    inserted = await parse_otel_summary(db, run_id, partial)

    assert inserted == 1
    rows = await _get_summaries(db, run_id)
    assert rows[0]["total_tokens"] == 5000
    assert rows[0]["model"] == "gpt-4o"
    assert rows[0]["input_tokens"] is None
    assert rows[0]["cost_usd"] is None


@pytest.mark.asyncio
async def test_partial_skill_data(tmp_db):
    """A skill entry missing most fields should still insert."""
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    data = {"skills": [{"skill_name": "review", "cost_usd": 1.0}]}
    inserted = await parse_otel_summary(db, run_id, data)

    assert inserted == 1
    rows = await _get_summaries(db, run_id)
    assert rows[0]["skill_name"] == "review"
    assert rows[0]["total_tokens"] is None


# ── Duplicate / idempotent insertion ─────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_flat_is_idempotent(tmp_db):
    """Inserting the same flat summary twice should not duplicate rows."""
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    first = await parse_otel_summary(db, run_id, FLAT_SUMMARY)
    second = await parse_otel_summary(db, run_id, FLAT_SUMMARY)

    # First call inserts, second is silently ignored
    assert first == 1
    # INSERT OR IGNORE means the second call's rowcount is 0
    assert second == 0
    assert await _count_summaries(db, run_id) == 1


@pytest.mark.asyncio
async def test_duplicate_skills_are_idempotent(tmp_db):
    """Inserting the same skill summary twice should not duplicate rows."""
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    first = await parse_otel_summary(db, run_id, SKILL_SUMMARY)
    second = await parse_otel_summary(db, run_id, SKILL_SUMMARY)

    assert first == 2
    assert second == 0
    assert await _count_summaries(db, run_id) == 2


# ── Empty / invalid data ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_dict_returns_zero(tmp_db):
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    assert await parse_otel_summary(db, run_id, {}) == 0
    assert await _count_summaries(db, run_id) == 0


@pytest.mark.asyncio
async def test_none_data_returns_zero(tmp_db):
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    assert await parse_otel_summary(db, run_id, None) == 0


@pytest.mark.asyncio
async def test_empty_skills_list_returns_zero(tmp_db):
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    assert await parse_otel_summary(db, run_id, {"skills": []}) == 0


@pytest.mark.asyncio
async def test_irrelevant_keys_returns_zero(tmp_db):
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    assert await parse_otel_summary(db, run_id, {"foo": "bar"}) == 0


@pytest.mark.asyncio
async def test_non_dict_skills_entry_skipped(tmp_db):
    """Non-dict entries in the skills list should be silently skipped."""
    db = await get_db()
    run_id = await _seed_pipeline_run(db)

    data = {"skills": ["not-a-dict", 42, None, {"skill_name": "valid", "cost_usd": 0.5}]}
    inserted = await parse_otel_summary(db, run_id, data)

    assert inserted == 1
    assert await _count_summaries(db, run_id) == 1
