"""impact area and reason on AI results

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_results', sa.Column('area', sa.String(length=40), nullable=True))
    op.add_column('ai_results', sa.Column('reason', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('ai_results', 'reason')
    op.drop_column('ai_results', 'area')
