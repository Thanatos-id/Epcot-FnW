"""add menu_items.image_url

Revision ID: a1c4e7d92f10
Revises: 6633b921fb60
Create Date: 2026-08-09 14:20:00.000000

Per-dish photos. Booths already had image_url; menu items did not, so the
individual plate/glass photos published on per-booth photo posts had nowhere
to land.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4e7d92f10'
down_revision = '6633b921fb60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('menu_items', sa.Column('image_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('menu_items', 'image_url')
