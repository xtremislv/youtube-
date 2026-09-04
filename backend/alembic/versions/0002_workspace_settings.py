"""workspace settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workspace_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instagram_scraping_enabled', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('workspace_settings')
