"""Tests for the admin API endpoints (db-health and purge)."""

import pytest

from backend.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_pipeline_and_run(db):
    """Insert a pipeline and a pipeline_run for foreign-key references."""
    await db.execute(
        "INSERT INTO pipelines (id, slug, name, repo_url, platform) VALUES (?, ?, ?, ?, ?)",
        (1, "admin-test", "Admin Test", "https://example.com/repo", "github"),
    )
    await db.execute(
        "INSERT INTO pipeline_runs (id, pipeline_id, external_id, status) VALUES (?, ?, ?, ?)",
        (1, 1, "run-admin-001", "success"),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# GET /api/admin/db-health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_health_returns_table_counts(client):
    db = await get_db()
    await _seed_pipeline_and_run(db)

    resp = await client.get("/api/admin/db-health")
    assert resp.status_code == 200
    body = resp.json()

    assert "database_size_bytes" in body
    assert isinstance(body["database_size_bytes"], int)
    assert body["database_size_bytes"] > 0

    counts = body["table_counts"]
    assert counts["pipelines"] == 1
    assert counts["pipeline_runs"] == 1
    assert counts["telemetry_spans"] == 0
    assert counts["telemetry_summaries"] == 0
    assert counts["run_commands"] == 0
    assert counts["run_packages"] == 0
    assert counts["run_containers"] == 0
    assert counts["container_sboms"] == 0
    assert counts["sbom_vulnerabilities"] == 0


@pytest.mark.asyncio
async def test_db_health_empty_database(client):
    resp = await client.get("/api/admin/db-health")
    assert resp.status_code == 200
    body = resp.json()
    counts = body["table_counts"]
    # All counts should be zero for a fresh database
    for table, count in counts.items():
        assert count == 0, f"Expected 0 for {table}, got {count}"


# ---------------------------------------------------------------------------
# POST /api/admin/purge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_returns_deletion_counts(client):
    db = await get_db()
    await _seed_pipeline_and_run(db)

    from datetime import datetime, timedelta, timezone
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()

    # Insert an old telemetry_span that should be purged
    await db.execute(
        "INSERT INTO telemetry_spans (pipeline_run_id, trace_id, span_id, created_at) VALUES (?, ?, ?, ?)",
        (1, "old-trace", "old-span", old_ts),
    )
    await db.commit()

    resp = await client.post("/api/admin/purge")
    assert resp.status_code == 200
    body = resp.json()

    assert body["telemetry_spans"] == 1
    assert body["run_commands"] == 0
    assert body["run_packages"] == 0
    assert body["run_containers"] == 0


@pytest.mark.asyncio
async def test_purge_nothing_to_delete(client):
    resp = await client.post("/api/admin/purge")
    assert resp.status_code == 200
    body = resp.json()

    assert body["telemetry_spans"] == 0
    assert body["run_commands"] == 0
    assert body["run_packages"] == 0
    assert body["run_containers"] == 0



# ---------------------------------------------------------------------------
# POST /api/admin/wipe-runtime-data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wipe_runtime_data_deletes_collected_data_and_preserves_configuration(client):
    db = await get_db()
    await _seed_pipeline_and_run(db)

    await db.execute(
        "INSERT INTO pipeline_images (pipeline_id, name, ref) VALUES (?, ?, ?)",
        (1, "runtime-test", "quay.io/test/runtime:latest"),
    )
    await db.execute(
        "INSERT INTO api_keys (key_hash, key_prefix, name, scopes) VALUES (?, ?, ?, ?)",
        ("hash", "obs_123", "test key", '["*"]'),
    )
    await db.execute(
        """INSERT INTO platform_credentials
            (name, platform, base_url, encrypted_token, scopes)
            VALUES (?, ?, ?, ?, ?)""",
        ("gitlab", "gitlab", "https://gitlab.example.com", "encrypted", '["api"]'),
    )
    await db.execute(
        "INSERT INTO telemetry_spans (pipeline_run_id, trace_id, span_id) VALUES (?, ?, ?)",
        (1, "trace", "span"),
    )
    await db.execute(
        "INSERT INTO telemetry_summaries (pipeline_run_id, total_tokens) VALUES (?, ?)",
        (1, 100),
    )
    await db.execute(
        """INSERT INTO otel_log_records
            (pipeline_run_id, trace_id, span_id, body) VALUES (?, ?, ?, ?)""",
        (1, "trace", "span", "log"),
    )
    await db.execute(
        """INSERT INTO otel_metric_points
            (pipeline_run_id, metric_name, metric_type, value) VALUES (?, ?, ?, ?)""",
        (1, "tokens", "gauge", 1.0),
    )
    await db.execute(
        "INSERT INTO telemetry_dimensions (pipeline_run_id, metric, dimension_key, dimension_value, value) VALUES (?, ?, ?, ?, ?)",
        (1, "cost", "model", "sonnet", 1.0),
    )
    await db.execute(
        "INSERT INTO run_commands (pipeline_run_id, step_order, command) VALUES (?, ?, ?)",
        (1, 1, "pytest"),
    )
    await db.execute(
        "INSERT INTO run_packages (pipeline_run_id, manager, name, version) VALUES (?, ?, ?, ?)",
        (1, "pip", "pytest", "1.0"),
    )
    await db.execute(
        "INSERT INTO run_containers (pipeline_run_id, image_ref) VALUES (?, ?)",
        (1, "quay.io/test/runtime:latest"),
    )
    await db.execute(
        "INSERT INTO job_artifacts (pipeline_run_id, source, file_path) VALUES (?, ?, ?)",
        (1, "ci_job", "result.md"),
    )
    await db.execute(
        "INSERT INTO trace_events (pipeline_run_id, source, event_type, content) VALUES (?, ?, ?, ?)",
        (1, "job", "tool_call", "called"),
    )
    await db.execute(
        "INSERT INTO trace_packages (pipeline_run_id, manager, name) VALUES (?, ?, ?)",
        (1, "pip", "httpx"),
    )
    await db.execute(
        "INSERT INTO trace_metadata (pipeline_run_id, key, value) VALUES (?, ?, ?)",
        (1, "agent", "codex"),
    )
    await db.execute(
        "INSERT INTO container_sboms (id, image_digest, image_ref, sbom) VALUES (?, ?, ?, ?)",
        (1, "sha256:test", "quay.io/test/runtime:latest", "{}"),
    )
    await db.execute(
        "INSERT INTO sbom_vulnerabilities (sbom_id, vuln_id) VALUES (?, ?)",
        (1, "CVE-0000"),
    )
    await db.execute(
        "INSERT INTO ci_jobs (id, pipeline_id, name) VALUES (?, ?, ?)",
        (1, 1, "test"),
    )
    await db.execute(
        "INSERT INTO ci_job_scripts (job_id, phase, step_order, command) VALUES (?, ?, ?, ?)",
        (1, "script", 1, "pytest"),
    )
    await db.execute(
        "INSERT INTO ci_includes (pipeline_id, include_type, file) VALUES (?, ?, ?)",
        (1, "local", ".gitlab-ci.yml"),
    )
    await db.execute(
        "INSERT INTO claims (id, claim_text, claim_type, claim_hash) VALUES (?, ?, ?, ?)",
        (1, "A claim", "architectural", "claim-hash"),
    )
    await db.execute(
        "INSERT INTO claim_sources (claim_id, pipeline_slug, source_file) VALUES (?, ?, ?)",
        (1, "admin-test", "result.md"),
    )
    await db.execute(
        "INSERT INTO claim_verdicts (claim_id, verdict) VALUES (?, ?)",
        (1, "supported"),
    )
    await db.execute(
        """INSERT INTO claim_extraction_runs
            (id, run_key, source_file, pipeline_slug, extractor_revision, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
        (1, "run-admin-claim", "result.md", "admin-test", "extractor-v2", "complete"),
    )
    await db.execute(
        """INSERT INTO claim_source_units
            (id, extraction_run_id, unit_key, unit_kind, source_locator, original_text)
            VALUES (?, ?, ?, ?, ?, ?)""",
        (1, 1, "unit-1", "sentence", "result.md:L1", "A claim"),
    )
    await db.execute(
        """INSERT INTO claim_selection_results
            (source_unit_id, classification, selected_text)
            VALUES (?, ?, ?)""",
        (1, "verifiable", "A claim"),
    )
    await db.execute(
        """INSERT INTO claim_stage_receipt_events
            (stage, scope_key, input_digest, skill_fqn, skill_revision, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
        ("extract-claims", "RFE-1", "sha256:input", "repo@main:extract-claims", "tree-1", "miss"),
    )
    await db.execute(
        "INSERT INTO collector_state (pipeline_id, last_run_external_id) VALUES (?, ?)",
        (1, "run-admin-001"),
    )
    await db.execute(
        "INSERT INTO chat_conversations (id, title) VALUES (?, ?)",
        ("conversation", "Test"),
    )
    await db.execute(
        "INSERT INTO chat_messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        ("message", "conversation", "user", "hello"),
    )
    await db.execute(
        "INSERT INTO kb_categories (id, name) VALUES (?, ?)",
        ("category", "General"),
    )
    await db.execute(
        "INSERT INTO kb_articles (id, category_id, title, slug, body) VALUES (?, ?, ?, ?, ?)",
        ("article", "category", "Article", "article", "body"),
    )
    await db.execute(
        "INSERT INTO data_sources (id, name, source_type) VALUES (?, ?, ?)",
        ("source", "Source", "filesystem"),
    )
    await db.commit()

    resp = await client.post("/api/admin/wipe-runtime-data")
    assert resp.status_code == 200
    body = resp.json()

    assert body["telemetry_spans"] == 1
    assert body["pipeline_runs"] == 1
    assert body["claims"] == 1
    assert body["claim_verdicts"] == 1
    assert body["claim_extraction_runs"] == 1
    assert body["claim_source_units"] == 1
    assert body["claim_selection_results"] == 1
    assert body["claim_stage_receipt_events"] == 1
    assert body["container_sboms"] == 1
    assert body["sbom_vulnerabilities"] == 1
    assert body["chat_messages"] == 1
    assert body["kb_articles"] == 1

    for table in (
        "pipeline_runs",
        "telemetry_spans",
        "telemetry_summaries",
        "otel_log_records",
        "otel_metric_points",
        "telemetry_dimensions",
        "run_commands",
        "run_packages",
        "run_containers",
        "job_artifacts",
        "trace_events",
        "trace_packages",
        "trace_metadata",
        "container_sboms",
        "sbom_vulnerabilities",
        "ci_jobs",
        "ci_includes",
        "claims",
        "claim_sources",
        "claim_verdicts",
        "claim_extraction_runs",
        "claim_source_units",
        "claim_selection_results",
        "claim_stage_receipt_events",
        "collector_state",
        "chat_conversations",
        "chat_messages",
        "kb_categories",
        "kb_articles",
        "data_sources",
    ):
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
        assert (await cursor.fetchone())[0] == 0, table

    for table in ("pipelines", "pipeline_images", "api_keys", "platform_credentials"):
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
        assert (await cursor.fetchone())[0] == 1, table
