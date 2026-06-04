"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pipelines (
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE pipeline_images (
            id INTEGER PRIMARY KEY,
            pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
            name TEXT,
            ref TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE pipeline_skills (
            id INTEGER PRIMARY KEY,
            pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
            repo_url TEXT NOT NULL,
            branch TEXT,
            purpose TEXT
        )
    """)

    op.execute("""
        CREATE TABLE pipeline_shared_libs (
            id INTEGER PRIMARY KEY,
            pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
            repo_url TEXT NOT NULL,
            purpose TEXT
        )
    """)

    op.execute("""
        CREATE TABLE pipeline_jira_contracts (
            id INTEGER PRIMARY KEY,
            pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
            project TEXT NOT NULL,
            labels_applied TEXT
        )
    """)

    op.execute("""
        CREATE TABLE pipeline_telemetry_config (
            id INTEGER PRIMARY KEY,
            pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
            collector_type TEXT,
            endpoint TEXT,
            summary_script TEXT,
            status TEXT DEFAULT 'active'
        )
    """)

    op.execute("""
        CREATE TABLE pipeline_artifact_config (
            id INTEGER PRIMARY KEY,
            pipeline_id INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
            results_repo TEXT,
            status TEXT DEFAULT 'active'
        )
    """)

    op.execute("""
        CREATE TABLE pipeline_runs (
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
            artifacts_scraped BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pipeline_id, external_id)
        )
    """)

    op.execute("""
        CREATE TABLE telemetry_spans (
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
        )
    """)

    op.execute("""
        CREATE TABLE telemetry_summaries (
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
        )
    """)

    op.execute("""
        CREATE TABLE mlflow_experiments (
            id INTEGER PRIMARY KEY,
            experiment_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            pipeline_id INTEGER REFERENCES pipelines(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE mlflow_runs (
            id INTEGER PRIMARY KEY,
            run_id TEXT UNIQUE NOT NULL,
            experiment_id TEXT REFERENCES mlflow_experiments(experiment_id),
            pipeline_run_id INTEGER REFERENCES pipeline_runs(id),
            status TEXT,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE mlflow_metrics (
            id INTEGER PRIMARY KEY,
            run_id TEXT REFERENCES mlflow_runs(run_id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value REAL NOT NULL,
            timestamp TIMESTAMP,
            step INTEGER DEFAULT 0
        )
    """)

    op.execute("""
        CREATE TABLE mlflow_params (
            id INTEGER PRIMARY KEY,
            run_id TEXT REFERENCES mlflow_runs(run_id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT
        )
    """)

    op.execute("""
        CREATE TABLE run_commands (
            id INTEGER PRIMARY KEY,
            pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
            step_order INTEGER NOT NULL,
            command TEXT NOT NULL,
            exit_code INTEGER,
            duration_ms INTEGER,
            source TEXT DEFAULT 'manifest',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE run_packages (
            id INTEGER PRIMARY KEY,
            pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
            manager TEXT NOT NULL,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            source TEXT DEFAULT 'manifest',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE run_containers (
            id INTEGER PRIMARY KEY,
            pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
            image_ref TEXT NOT NULL,
            image_digest TEXT,
            platform TEXT,
            source TEXT DEFAULT 'manifest',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE container_sboms (
            id INTEGER PRIMARY KEY,
            image_digest TEXT UNIQUE NOT NULL,
            image_ref TEXT NOT NULL,
            format TEXT DEFAULT 'spdx-json',
            sbom TEXT NOT NULL,
            generator TEXT,
            generated_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE sbom_vulnerabilities (
            id INTEGER PRIMARY KEY,
            sbom_id INTEGER REFERENCES container_sboms(id) ON DELETE CASCADE,
            vuln_id TEXT NOT NULL,
            package_name TEXT,
            installed_version TEXT,
            fixed_version TEXT,
            severity TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    op.execute("""
        CREATE TABLE collector_state (
            id INTEGER PRIMARY KEY,
            pipeline_id INTEGER REFERENCES pipelines(id),
            last_collected_at TIMESTAMP,
            last_run_external_id TEXT,
            last_error TEXT,
            consecutive_failures INTEGER DEFAULT 0
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS collector_state")
    op.execute("DROP TABLE IF EXISTS sbom_vulnerabilities")
    op.execute("DROP TABLE IF EXISTS container_sboms")
    op.execute("DROP TABLE IF EXISTS run_containers")
    op.execute("DROP TABLE IF EXISTS run_packages")
    op.execute("DROP TABLE IF EXISTS run_commands")
    op.execute("DROP TABLE IF EXISTS mlflow_params")
    op.execute("DROP TABLE IF EXISTS mlflow_metrics")
    op.execute("DROP TABLE IF EXISTS mlflow_runs")
    op.execute("DROP TABLE IF EXISTS mlflow_experiments")
    op.execute("DROP TABLE IF EXISTS telemetry_summaries")
    op.execute("DROP TABLE IF EXISTS telemetry_spans")
    op.execute("DROP TABLE IF EXISTS pipeline_runs")
    op.execute("DROP TABLE IF EXISTS pipeline_artifact_config")
    op.execute("DROP TABLE IF EXISTS pipeline_telemetry_config")
    op.execute("DROP TABLE IF EXISTS pipeline_jira_contracts")
    op.execute("DROP TABLE IF EXISTS pipeline_shared_libs")
    op.execute("DROP TABLE IF EXISTS pipeline_skills")
    op.execute("DROP TABLE IF EXISTS pipeline_images")
    op.execute("DROP TABLE IF EXISTS pipelines")
