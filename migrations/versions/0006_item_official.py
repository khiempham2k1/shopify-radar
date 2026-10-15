"""official flag on items (Shopify's own sources and domains)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('items', sa.Column('official', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(op.f('ix_items_official'), 'items', ['official'], unique=False)
    # Platform sources are Shopify's own; items from Shopify domains elsewhere are flagged on the next scoring run.
    op.execute("UPDATE items SET official = true WHERE source_id IN (SELECT id FROM sources WHERE kind = 'platform')")


def downgrade() -> None:
    op.drop_index(op.f('ix_items_official'), table_name='items')
    op.drop_column('items', 'official')
