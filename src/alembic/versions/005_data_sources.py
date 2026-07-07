"""Add data_sources table for intelligence configuration

Revision ID: 005
Revises: 004
Create Date: 2026-06-24

"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
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
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_data_sources_type ON data_sources(source_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_data_sources_status ON data_sources(status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_data_sources_status")
    op.execute("DROP INDEX IF EXISTS idx_data_sources_type")
    op.execute("DROP TABLE IF EXISTS data_sources")
