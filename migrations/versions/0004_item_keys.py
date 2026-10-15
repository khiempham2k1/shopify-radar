"""dedupe keys shared across sources

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('item_keys',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_item_keys_item_id'), 'item_keys', ['item_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_item_keys_item_id'), table_name='item_keys')
    op.drop_table('item_keys')
