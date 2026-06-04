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
    claim_id INTEGER REFERENCES claims(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL,
    confidence INTEGER,
    evidence_summary TEXT,
    evidence_source TEXT,
    evidence_detail TEXT,
    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_claim_verdicts_claim ON claim_verdicts(claim_id);

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
"""


async def init_schema(db: aiosqlite.Connection) -> None:
    """Apply schema directly (for tests and first-run initialization)."""
    await db.executescript(_SCHEMA_SQL)
    await db.commit()
    await db.execute("PRAGMA foreign_keys=ON")
