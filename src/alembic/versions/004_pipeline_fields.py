"""Add group, display_order, jobs, job_patterns to pipelines

Revision ID: 004
Revises: 003
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('ALTER TABLE pipelines ADD COLUMN "group" TEXT')
    op.execute('ALTER TABLE pipelines ADD COLUMN display_order INTEGER')
    op.execute('ALTER TABLE pipelines ADD COLUMN jobs TEXT')
    op.execute('ALTER TABLE pipelines ADD COLUMN job_patterns TEXT')


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN before 3.35 -- just leave them
    pass
