"""who a classified item affects: theme code, partners, merchants

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ai_results', sa.Column('affects', sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column('ai_results', 'affects')
