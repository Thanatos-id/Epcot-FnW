"""add booths.origin and menu_items.origin

Revision ID: e5a8c3d71b24
Revises: d4f7b2c68e91
Create Date: 2026-08-30 12:00:00.000000

Records the difference between a row a crawled source vouches for and one a
person entered by hand, because reconcile.py has to treat the two opposite
ways.

Every canonical row until now traced back to at least one crawled page, and
pipeline/reconcile.py retires anything left supported only by superseded
pages. The `manual` source is excluded from that calculation on purpose - a
coordinate surveyed last season must not be what keeps a defunct booth alive
- which is exactly right for a *correction* to a crawled row, and exactly
wrong for a row that only ever existed because somebody typed it. Without
this column a hand-added dish is retired by the first crawl after it lands.

Existing rows are all crawled by definition: nothing could create a canonical
row but a source, and the studio that can does not exist before this
migration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5a8c3d71b24'
down_revision = 'd4f7b2c68e91'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('booths', 'menu_items'):
        op.add_column(
            table,
            sa.Column(
                'origin',
                sa.Text(),
                nullable=False,
                server_default='crawled',
            ),
        )


def downgrade() -> None:
    for table in ('booths', 'menu_items'):
        op.drop_column(table, 'origin')
