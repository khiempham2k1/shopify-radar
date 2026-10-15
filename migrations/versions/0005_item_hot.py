"""item hot score for the Feed

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('items', sa.Column('hot', sa.Float(), nullable=False, server_default='0'))
    op.create_index(op.f('ix_items_hot'), 'items', ['hot'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_items_hot'), table_name='items')
    op.drop_column('items', 'hot')
