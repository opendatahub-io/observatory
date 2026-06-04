"""platform_credentials table

Revision ID: 003
Revises: 002
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE platform_credentials (
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
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_credentials")
