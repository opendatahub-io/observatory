import hashlib
import json

import aiosqlite

import backend.config

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized — call connect() first")
    return _db


async def connect() -> aiosqlite.Connection:
    global _db
    backend.config.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(backend.config.settings.database_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.execute("PRAGMA busy_timeout=5000")
    return _db


async def disconnect() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipelines (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    owner TEXT,
    repo_url TEXT NOT NULL,
    platform TEXT NOT NULL,
    platform_project_id TEXT,
    cron TEXT,
    expected_interval_minutes INTEGER,
    timeout_minutes INTEGER,
    status TEXT DEFAULT 'production',
    "group" TEXT,
    display_order INTEGER,
    jobs TEXT,
    job_patterns TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_images (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    name TEXT,
    ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_skills (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    repo_url TEXT NOT NULL,
    branch TEXT,
    purpose TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_shared_libs (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    repo_url TEXT NOT NULL,
    purpose TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_jira_contracts (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    project TEXT NOT NULL,
    labels_applied TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_telemetry_config (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    collector_type TEXT,
    endpoint TEXT,
    summary_script TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS pipeline_artifact_config (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    results_repo TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    job TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds INTEGER,
    status TEXT NOT NULL,
    ref TEXT,
    web_url TEXT,
    queued_at TIMESTAMP,
    artifacts_scraped BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(pipeline_id, external_id)
);

CREATE TABLE IF NOT EXISTS telemetry_spans (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    trace_id TEXT,
    span_id TEXT,
    parent_span_id TEXT,
    operation_name TEXT,
    service_name TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_ms INTEGER,
    status_code TEXT,
    attributes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telemetry_summaries (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    total_tokens INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    model TEXT,
    skill_name TEXT,
    duration_ms INTEGER,
    source TEXT DEFAULT 'artifact',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mlflow_experiments (
    id INTEGER PRIMARY KEY,
    experiment_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    pipeline_id INTEGER REFERENCES pipelines(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mlflow_runs (
    id INTEGER PRIMARY KEY,
    run_id TEXT UNIQUE NOT NULL,
    experiment_id TEXT REFERENCES mlflow_experiments(experiment_id),
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id),
    status TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mlflow_metrics (
    id INTEGER PRIMARY KEY,
    run_id TEXT REFERENCES mlflow_runs(run_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    timestamp TIMESTAMP,
    step INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mlflow_params (
    id INTEGER PRIMARY KEY,
    run_id TEXT REFERENCES mlflow_runs(run_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT
);

CREATE TABLE IF NOT EXISTS run_commands (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    command TEXT NOT NULL,
    exit_code INTEGER,
    duration_ms INTEGER,
    source TEXT DEFAULT 'manifest',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_packages (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    manager TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    source TEXT DEFAULT 'manifest',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_containers (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    image_ref TEXT NOT NULL,
    image_digest TEXT,
    platform TEXT,
    source TEXT DEFAULT 'manifest',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS container_sboms (
    id INTEGER PRIMARY KEY,
    image_digest TEXT UNIQUE NOT NULL,
    image_ref TEXT NOT NULL,
    format TEXT DEFAULT 'spdx-json',
    sbom TEXT NOT NULL,
    generator TEXT,
    generated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sbom_vulnerabilities (
    id INTEGER PRIMARY KEY,
    sbom_id INTEGER REFERENCES container_sboms(id) ON DELETE CASCADE,
    vuln_id TEXT NOT NULL,
    package_name TEXT,
    installed_version TEXT,
    fixed_version TEXT,
    severity TEXT,
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telemetry_dimensions (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    dimension_key TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_dims_run ON telemetry_dimensions(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_dims_metric ON telemetry_dimensions(metric, dimension_key);

CREATE TABLE IF NOT EXISTS job_artifacts (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_ref TEXT,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    mime_type TEXT,
    content BLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_job_artifacts_run ON job_artifacts(pipeline_run_id);

CREATE TABLE IF NOT EXISTS trace_events (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT,
    content TEXT,
    line_number INTEGER
);
CREATE INDEX IF NOT EXISTS idx_trace_events_run ON trace_events(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON trace_events(event_type);

CREATE TABLE IF NOT EXISTS trace_packages (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    manager TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT,
    arch TEXT,
    repo TEXT
);
CREATE INDEX IF NOT EXISTS idx_trace_packages_run ON trace_packages(pipeline_run_id);

CREATE TABLE IF NOT EXISTS trace_metadata (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE(pipeline_run_id, key)
);

CREATE TABLE IF NOT EXISTS ci_jobs (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    stage TEXT,
    image TEXT,
    timeout TEXT,
    extends TEXT,
    resource_group TEXT,
    allow_failure BOOLEAN DEFAULT FALSE,
    UNIQUE(pipeline_id, name)
);

CREATE TABLE IF NOT EXISTS ci_job_tags (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES ci_jobs(id) ON DELETE CASCADE,
    tag TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ci_job_variables (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES ci_jobs(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    masked BOOLEAN DEFAULT FALSE,
    UNIQUE(job_id, key)
);

CREATE TABLE IF NOT EXISTS ci_job_scripts (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES ci_jobs(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    command TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ci_includes (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    include_type TEXT NOT NULL,
    project TEXT,
    file TEXT,
    ref TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY,
    claim_text TEXT NOT NULL,
    claim_type TEXT,
    claim_hash TEXT UNIQUE NOT NULL,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);

CREATE TABLE IF NOT EXISTS claim_sources (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER REFERENCES claims(id) ON DELETE CASCADE,
    pipeline_slug TEXT NOT NULL,
    source_file TEXT NOT NULL,
    original_text TEXT,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_sources_claim ON claim_sources(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_sources_pipeline ON claim_sources(pipeline_slug);

CREATE TABLE IF NOT EXISTS claim_jira_keys (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER REFERENCES claims(id) ON DELETE CASCADE,
    jira_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_jira_keys_claim ON claim_jira_keys(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_jira_keys_key ON claim_jira_keys(jira_key);

CREATE TABLE IF NOT EXISTS claim_verdicts (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER UNIQUE REFERENCES claims(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL,
    confidence INTEGER,
    evidence_summary TEXT,
    evidence_source TEXT,
    evidence_detail TEXT,
    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_verdicts_claim ON claim_verdicts(claim_id);

CREATE TABLE IF NOT EXISTS claim_explanations (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER UNIQUE REFERENCES claims(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    explanation TEXT NOT NULL,
    sources_used TEXT,
    explained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_explanations_claim ON claim_explanations(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_explanations_category ON claim_explanations(category);

CREATE TABLE IF NOT EXISTS claim_extraction_runs (
    id INTEGER PRIMARY KEY,
    run_key TEXT UNIQUE NOT NULL,
    payload_digest TEXT,
    source_file TEXT NOT NULL,
    pipeline_slug TEXT NOT NULL,
    artifact_type TEXT,
    artifact_digest TEXT,
    extractor_revision TEXT NOT NULL,
    repository_revision TEXT,
    model TEXT,
    harness TEXT,
    configuration_digest TEXT,
    configuration TEXT,
    token_count INTEGER,
    cost_usd REAL,
    duration_seconds REAL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_extraction_runs_source ON claim_extraction_runs(source_file);

CREATE TABLE IF NOT EXISTS claim_source_units (
    id INTEGER PRIMARY KEY,
    extraction_run_id INTEGER NOT NULL REFERENCES claim_extraction_runs(id) ON DELETE CASCADE,
    unit_key TEXT NOT NULL,
    unit_kind TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    original_text TEXT NOT NULL,
    heading_path TEXT,
    preceding_context TEXT,
    following_context TEXT,
    list_preamble TEXT,
    UNIQUE(extraction_run_id, unit_key)
);
CREATE INDEX IF NOT EXISTS idx_claim_source_units_run ON claim_source_units(extraction_run_id);

CREATE TABLE IF NOT EXISTS claim_selection_results (
    id INTEGER PRIMARY KEY,
    source_unit_id INTEGER UNIQUE NOT NULL REFERENCES claim_source_units(id) ON DELETE CASCADE,
    classification TEXT NOT NULL,
    selected_text TEXT,
    rationale TEXT,
    evaluator_revision TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS claim_ambiguity_results (
    id INTEGER PRIMARY KEY,
    source_unit_id INTEGER UNIQUE NOT NULL REFERENCES claim_source_units(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    ambiguity_types TEXT,
    clarified_text TEXT,
    resolution_context TEXT,
    rationale TEXT,
    evaluator_revision TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS claim_occurrences (
    id INTEGER PRIMARY KEY,
    normalized_claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    source_unit_id INTEGER NOT NULL REFERENCES claim_source_units(id) ON DELETE CASCADE,
    legacy_source_id INTEGER UNIQUE REFERENCES claim_sources(id) ON DELETE SET NULL,
    claim_text TEXT NOT NULL,
    original_text TEXT,
    claim_type TEXT,
    modality TEXT,
    product_version TEXT,
    temporal_scope TEXT,
    clarification TEXT,
    accepted BOOLEAN NOT NULL DEFAULT TRUE,
    occurrence_hash TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(normalized_claim_id, source_unit_id, claim_text)
);
CREATE INDEX IF NOT EXISTS idx_claim_occurrences_claim ON claim_occurrences(normalized_claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_occurrences_unit ON claim_occurrences(source_unit_id);

CREATE TABLE IF NOT EXISTS claim_occurrence_jira_keys (
    id INTEGER PRIMARY KEY,
    claim_occurrence_id INTEGER NOT NULL
      REFERENCES claim_occurrences(id) ON DELETE CASCADE,
    jira_key TEXT NOT NULL,
    UNIQUE(claim_occurrence_id, jira_key)
);
CREATE INDEX IF NOT EXISTS idx_claim_occurrence_jira_occurrence
    ON claim_occurrence_jira_keys(claim_occurrence_id);
CREATE INDEX IF NOT EXISTS idx_claim_occurrence_jira_key
    ON claim_occurrence_jira_keys(jira_key);

CREATE TABLE IF NOT EXISTS claim_extraction_evaluations (
    id INTEGER PRIMARY KEY,
    claim_occurrence_id INTEGER NOT NULL REFERENCES claim_occurrences(id) ON DELETE CASCADE,
    evaluator_revision TEXT NOT NULL,
    entailed BOOLEAN,
    entailment_rationale TEXT,
    coverage_result TEXT,
    decontextualization_result TEXT,
    maximally_contextualized_claim TEXT,
    extracted_retrieval_digest TEXT,
    comparison_retrieval_digest TEXT,
    evidence_context_digest TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_extraction_evals_occurrence
    ON claim_extraction_evaluations(claim_occurrence_id);

CREATE TABLE IF NOT EXISTS claim_coverage_elements (
    id INTEGER PRIMARY KEY,
    extraction_evaluation_id INTEGER NOT NULL
      REFERENCES claim_extraction_evaluations(id) ON DELETE CASCADE,
    element_text TEXT NOT NULL,
    element_kind TEXT NOT NULL,
    coverage TEXT NOT NULL,
    rationale TEXT,
    UNIQUE(extraction_evaluation_id, element_text, element_kind)
);
CREATE INDEX IF NOT EXISTS idx_claim_coverage_elements_evaluation
    ON claim_coverage_elements(extraction_evaluation_id);

CREATE TABLE IF NOT EXISTS claim_verification_runs (
    id INTEGER PRIMARY KEY,
    claim_occurrence_id INTEGER NOT NULL REFERENCES claim_occurrences(id) ON DELETE CASCADE,
    legacy_verdict_id INTEGER REFERENCES claim_verdicts(id) ON DELETE SET NULL,
    verifier_revision TEXT NOT NULL,
    repository_revision TEXT,
    model TEXT,
    harness TEXT,
    configuration_digest TEXT,
    evidence_context_digest TEXT,
    verdict TEXT NOT NULL,
    severity TEXT,
    confidence INTEGER,
    evidence_summary TEXT,
    token_count INTEGER,
    cost_usd REAL,
    duration_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_verification_runs_occurrence
    ON claim_verification_runs(claim_occurrence_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_verification_runs_legacy
    ON claim_verification_runs(claim_occurrence_id, legacy_verdict_id)
    WHERE legacy_verdict_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS claim_explanation_runs (
    id INTEGER PRIMARY KEY,
    verification_run_id INTEGER NOT NULL REFERENCES claim_verification_runs(id) ON DELETE CASCADE,
    legacy_explanation_id INTEGER REFERENCES claim_explanations(id) ON DELETE SET NULL,
    explainer_revision TEXT NOT NULL,
    repository_revision TEXT,
    model TEXT,
    harness TEXT,
    configuration_digest TEXT,
    category TEXT NOT NULL,
    improvement_target TEXT,
    explanation TEXT NOT NULL,
    contributing_factors TEXT,
    alternative_explanations TEXT,
    remediation TEXT,
    regression_test TEXT,
    human_review_required BOOLEAN NOT NULL DEFAULT FALSE,
    token_count INTEGER,
    cost_usd REAL,
    duration_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_explanation_runs_verification
    ON claim_explanation_runs(verification_run_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_explanation_runs_legacy
    ON claim_explanation_runs(verification_run_id, legacy_explanation_id)
    WHERE legacy_explanation_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS claim_evidence_records (
    id INTEGER PRIMARY KEY,
    stage TEXT NOT NULL,
    stage_run_id INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    uri TEXT,
    repository_revision TEXT,
    artifact_digest TEXT,
    source_locator TEXT,
    query TEXT,
    excerpt TEXT,
    relationship TEXT,
    authority TEXT,
    product_version TEXT,
    retrieved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_stage
    ON claim_evidence_records(stage, stage_run_id);

CREATE TABLE IF NOT EXISTS claim_human_overrides (
    id INTEGER PRIMARY KEY,
    claim_occurrence_id INTEGER NOT NULL REFERENCES claim_occurrences(id) ON DELETE CASCADE,
    verification_run_id INTEGER NOT NULL REFERENCES claim_verification_runs(id),
    actor TEXT NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_human_overrides_occurrence
    ON claim_human_overrides(claim_occurrence_id, created_at DESC);

CREATE TABLE IF NOT EXISTS claim_regression_runs (
    id INTEGER PRIMARY KEY,
    explanation_run_id INTEGER NOT NULL REFERENCES claim_explanation_runs(id) ON DELETE CASCADE,
    dataset_fqn TEXT NOT NULL,
    implementation_revision TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics TEXT,
    run_uri TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_regression_runs_explanation
    ON claim_regression_runs(explanation_run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS claim_stage_receipt_events (
    id INTEGER PRIMARY KEY,
    stage TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    evidence_context_digest TEXT,
    skill_fqn TEXT NOT NULL,
    skill_revision TEXT NOT NULL,
    model TEXT,
    harness TEXT,
    configuration_digest TEXT,
    status TEXT NOT NULL,
    agent_job_avoided BOOLEAN NOT NULL DEFAULT FALSE,
    details TEXT,
    observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_receipt_events_scope
    ON claim_stage_receipt_events(scope_key, stage, observed_at DESC);

CREATE TABLE IF NOT EXISTS otel_log_records (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    trace_id TEXT,
    span_id TEXT,
    severity_number INTEGER,
    severity_text TEXT,
    body TEXT,
    attributes TEXT,
    resource_attrs TEXT,
    observed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_otel_logs_run ON otel_log_records(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_otel_logs_trace ON otel_log_records(trace_id);

CREATE TABLE IF NOT EXISTS otel_metric_points (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    value REAL,
    attributes TEXT,
    resource_attrs TEXT,
    recorded_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_otel_metrics_run ON otel_metric_points(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_otel_metrics_name ON otel_metric_points(metric_name);

CREATE TABLE IF NOT EXISTS collector_state (
    id INTEGER PRIMARY KEY,
    pipeline_id INTEGER REFERENCES pipelines(id),
    last_collected_at TIMESTAMP,
    last_run_external_id TEXT,
    last_error TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    last_data_repo_sha TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY,
    key_hash TEXT UNIQUE NOT NULL,
    key_prefix TEXT NOT NULL,
    name TEXT NOT NULL,
    scopes TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS platform_credentials (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    base_url TEXT NOT NULL,
    encrypted_token TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '["*"]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Chat tables
CREATE TABLE IF NOT EXISTS chat_conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool_use', 'tool_result')),
    content TEXT NOT NULL,
    metadata TEXT,
    blocks TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id, created_at);

-- Knowledge Base tables
CREATE TABLE IF NOT EXISTS kb_categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kb_articles (
    id TEXT PRIMARY KEY,
    category_id TEXT REFERENCES kb_categories(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    tags TEXT,
    status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published', 'archived')),
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'agent_suggested', 'imported')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kb_articles_category ON kb_articles(category_id);
CREATE INDEX IF NOT EXISTS idx_kb_articles_status ON kb_articles(status);
CREATE INDEX IF NOT EXISTS idx_kb_articles_slug ON kb_articles(slug);

CREATE TABLE IF NOT EXISTS data_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    endpoint TEXT,
    description TEXT,
    config TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    last_health_check TEXT,
    last_health_status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_data_sources_type ON data_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_data_sources_status ON data_sources(status);
"""


async def _ensure_fts(db: aiosqlite.Connection) -> None:
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='kb_articles_fts'"
    )
    if not await cursor.fetchone():
        await db.executescript(
            """CREATE VIRTUAL TABLE kb_articles_fts USING fts5(
                title, body, tags,
                content='kb_articles',
                content_rowid='rowid'
            );"""
        )
        await db.commit()


async def _backfill_claim_assurance(db: aiosqlite.Connection) -> None:
    cursor = await db.execute(
        """SELECT cs.id AS source_id, cs.claim_id, cs.pipeline_slug,
                  cs.source_file, cs.original_text, cs.extracted_at,
                  c.claim_text, c.claim_type
           FROM claim_sources cs
           JOIN claims c ON c.id = cs.claim_id
           ORDER BY cs.id"""
    )
    for row in await cursor.fetchall():
        run_key = f"legacy-source:{row['source_id']}"
        await db.execute(
            """INSERT OR IGNORE INTO claim_extraction_runs
               (run_key, source_file, pipeline_slug, artifact_type, extractor_revision,
                status, started_at, completed_at)
               VALUES (?, ?, ?, ?, 'legacy-backfill', 'complete', ?, ?)""",
            (run_key, row["source_file"], row["pipeline_slug"],
             row["pipeline_slug"], row["extracted_at"], row["extracted_at"]),
        )
        run_cursor = await db.execute(
            "SELECT id FROM claim_extraction_runs WHERE run_key = ?", (run_key,)
        )
        extraction_run_id = (await run_cursor.fetchone())["id"]
        unit_key = f"legacy-source-unit:{row['source_id']}"
        await db.execute(
            """INSERT OR IGNORE INTO claim_source_units
               (extraction_run_id, unit_key, unit_kind, source_locator,
                original_text, heading_path, preceding_context, following_context)
               VALUES (?, ?, 'legacy', ?, ?, '[]', '[]', '[]')""",
            (
                extraction_run_id,
                unit_key,
                row["source_file"],
                row["original_text"] or row["claim_text"],
            ),
        )
        unit_cursor = await db.execute(
            "SELECT id FROM claim_source_units WHERE extraction_run_id = ? AND unit_key = ?",
            (extraction_run_id, unit_key),
        )
        source_unit_id = (await unit_cursor.fetchone())["id"]
        occurrence_hash = hashlib.sha256(
            f"legacy:{row['source_id']}:{row['claim_id']}".encode()
        ).hexdigest()
        await db.execute(
            """INSERT OR IGNORE INTO claim_occurrences
               (normalized_claim_id, source_unit_id, legacy_source_id,
                claim_text, original_text, claim_type, occurrence_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["claim_id"],
                source_unit_id,
                row["source_id"],
                row["claim_text"],
                row["original_text"],
                row["claim_type"],
                occurrence_hash,
                row["extracted_at"],
            ),
        )

    cursor = await db.execute(
        """SELECT co.id AS occurrence_id, cv.*
           FROM claim_occurrences co
           JOIN claim_verdicts cv ON cv.claim_id = co.normalized_claim_id"""
    )
    for row in await cursor.fetchall():
        await db.execute(
            """INSERT OR IGNORE INTO claim_verification_runs
               (claim_occurrence_id, legacy_verdict_id, verifier_revision,
                verdict, confidence, evidence_summary, created_at)
               VALUES (?, ?, 'legacy-backfill', ?, ?, ?, ?)""",
            (
                row["occurrence_id"],
                row["id"],
                row["verdict"],
                row["confidence"],
                row["evidence_summary"],
                row["verified_at"],
            ),
        )
        verification_cursor = await db.execute(
            """SELECT id FROM claim_verification_runs
               WHERE claim_occurrence_id = ? AND legacy_verdict_id = ?""",
            (row["occurrence_id"], row["id"]),
        )
        verification_run_id = (await verification_cursor.fetchone())["id"]
        if row["evidence_detail"] or row["evidence_source"]:
            await db.execute(
                """INSERT INTO claim_evidence_records
                   (stage, stage_run_id, evidence_type, excerpt, authority)
                   SELECT 'verification', ?, 'legacy', ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM claim_evidence_records
                       WHERE stage = 'verification' AND stage_run_id = ?
                         AND evidence_type = 'legacy'
                   )""",
                (
                    verification_run_id,
                    row["evidence_detail"],
                    row["evidence_source"],
                    verification_run_id,
                ),
            )

    cursor = await db.execute(
        """SELECT co.id AS occurrence_id, ce.*
           FROM claim_occurrences co
           JOIN claim_explanations ce ON ce.claim_id = co.normalized_claim_id"""
    )
    for row in await cursor.fetchall():
        verification_cursor = await db.execute(
            """SELECT id FROM claim_verification_runs
               WHERE claim_occurrence_id = ? ORDER BY created_at DESC, id DESC LIMIT 1""",
            (row["occurrence_id"],),
        )
        verification = await verification_cursor.fetchone()
        if not verification:
            continue
        await db.execute(
            """INSERT OR IGNORE INTO claim_explanation_runs
               (verification_run_id, legacy_explanation_id, explainer_revision,
                category, explanation, contributing_factors, created_at)
               VALUES (?, ?, 'legacy-backfill', ?, ?, ?, ?)""",
            (
                verification["id"],
                row["id"],
                row["category"],
                row["explanation"],
                json.dumps({"legacy_sources_used": row["sources_used"]}),
                row["explained_at"],
            ),
        )

    await db.execute(
        """UPDATE claim_human_overrides AS override
           SET verification_run_id = (
             SELECT verification.id
             FROM claim_verification_runs AS verification
             WHERE verification.claim_occurrence_id = override.claim_occurrence_id
               AND verification.created_at <= override.created_at
             ORDER BY verification.created_at DESC, verification.id DESC
             LIMIT 1
           )
           WHERE verification_run_id IS NULL"""
    )
    await db.commit()


async def _ensure_claim_assurance_columns(db: aiosqlite.Connection) -> None:
    """Apply additive columns for databases created by an earlier v2 draft."""
    cursor = await db.execute("PRAGMA table_info(claim_verification_runs)")
    columns = {row["name"] for row in await cursor.fetchall()}
    if "severity" not in columns:
        await db.execute("ALTER TABLE claim_verification_runs ADD COLUMN severity TEXT")
    for name, data_type in (
        ("repository_revision", "TEXT"),
        ("model", "TEXT"),
        ("harness", "TEXT"),
        ("configuration_digest", "TEXT"),
        ("token_count", "INTEGER"),
        ("cost_usd", "REAL"),
        ("duration_seconds", "REAL"),
    ):
        if name not in columns:
            await db.execute(
                f"ALTER TABLE claim_verification_runs ADD COLUMN {name} {data_type}"
            )
    cursor = await db.execute("PRAGMA table_info(claim_extraction_runs)")
    extraction_columns = {row["name"] for row in await cursor.fetchall()}
    for name, data_type in (
        ("payload_digest", "TEXT"),
        ("artifact_type", "TEXT"),
        ("repository_revision", "TEXT"),
        ("token_count", "INTEGER"),
        ("cost_usd", "REAL"),
        ("duration_seconds", "REAL"),
    ):
        if name not in extraction_columns:
            await db.execute(f"ALTER TABLE claim_extraction_runs ADD COLUMN {name} {data_type}")
    cursor = await db.execute("PRAGMA table_info(claim_stage_receipt_events)")
    receipt_columns = {row["name"] for row in await cursor.fetchall()}
    if "harness" not in receipt_columns:
        await db.execute("ALTER TABLE claim_stage_receipt_events ADD COLUMN harness TEXT")
    cursor = await db.execute("PRAGMA table_info(claim_extraction_evaluations)")
    evaluation_columns = {row["name"] for row in await cursor.fetchall()}
    for name in (
        "maximally_contextualized_claim",
        "extracted_retrieval_digest",
        "comparison_retrieval_digest",
    ):
        if name not in evaluation_columns:
            await db.execute(
                f"ALTER TABLE claim_extraction_evaluations ADD COLUMN {name} TEXT"
            )
    cursor = await db.execute("PRAGMA table_info(claim_occurrences)")
    occurrence_columns = {row["name"] for row in await cursor.fetchall()}
    if "accepted" not in occurrence_columns:
        await db.execute(
            "ALTER TABLE claim_occurrences ADD COLUMN accepted BOOLEAN NOT NULL DEFAULT TRUE"
        )
    cursor = await db.execute("PRAGMA table_info(claim_explanation_runs)")
    explanation_columns = {row["name"] for row in await cursor.fetchall()}
    if "human_review_required" not in explanation_columns:
        await db.execute(
            """ALTER TABLE claim_explanation_runs
               ADD COLUMN human_review_required BOOLEAN NOT NULL DEFAULT FALSE"""
        )
    for name, data_type in (
        ("repository_revision", "TEXT"),
        ("model", "TEXT"),
        ("harness", "TEXT"),
        ("configuration_digest", "TEXT"),
        ("token_count", "INTEGER"),
        ("cost_usd", "REAL"),
        ("duration_seconds", "REAL"),
    ):
        if name not in explanation_columns:
            await db.execute(
                f"ALTER TABLE claim_explanation_runs ADD COLUMN {name} {data_type}"
            )
    await db.commit()


async def _ensure_chat_blocks_column(db: aiosqlite.Connection) -> None:
    """Add blocks column to chat_messages and migrate existing messages."""
    cursor = await db.execute("PRAGMA table_info(chat_messages)")
    columns = {row["name"] for row in await cursor.fetchall()}
    if "blocks" in columns:
        return

    await db.execute("ALTER TABLE chat_messages ADD COLUMN blocks TEXT")

    cursor = await db.execute(
        "SELECT id, role, content, metadata FROM chat_messages WHERE role = 'assistant'"
    )
    rows = await cursor.fetchall()
    for row in rows:
        msg = dict(row)
        tool_calls = []
        meta = msg.get("metadata")
        if meta:
            try:
                parsed = json.loads(meta)
                if isinstance(parsed, dict):
                    tool_calls = parsed.get("tool_calls", [])
            except (json.JSONDecodeError, TypeError):
                pass

        blocks = []
        for i, tc in enumerate(tool_calls):
            blocks.append({
                "id": f"migrated-tool-{i}",
                "type": "tool",
                "tool": tc.get("tool", "unknown"),
                "input": tc.get("input", {}),
                "result": tc.get("result"),
                "status": "succeeded" if tc.get("result") is not None else "failed",
            })
        if msg["content"]:
            blocks.append({
                "id": "migrated-answer",
                "type": "answer",
                "text": msg["content"],
                "activity_order": "legacy_unavailable",
            })
        if blocks:
            await db.execute(
                "UPDATE chat_messages SET blocks = ? WHERE id = ?",
                (json.dumps(blocks), msg["id"]),
            )
    await db.commit()


async def init_schema(db: aiosqlite.Connection) -> None:
    """Apply schema directly (for tests and first-run initialization)."""
    await db.executescript(_SCHEMA_SQL)
    await db.commit()
    await _ensure_fts(db)
    await _ensure_claim_assurance_columns(db)
    await _backfill_claim_assurance(db)
    await _ensure_chat_blocks_column(db)
    await db.execute("PRAGMA foreign_keys=ON")
