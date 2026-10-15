"""item priority topics

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('items', sa.Column('priority', sa.String(length=300), nullable=True))
    op.create_index(op.f('ix_items_priority'), 'items', ['priority'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_items_priority'), table_name='items')
    op.drop_column('items', 'priority')
