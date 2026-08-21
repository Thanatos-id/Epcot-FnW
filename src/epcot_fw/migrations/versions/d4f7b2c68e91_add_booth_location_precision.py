"""add booths.location_precision

Revision ID: d4f7b2c68e91
Revises: c3e6a91b8d52
Create Date: 2026-08-21 23:55:00.000000

Coordinates are about to arrive from two very different places: a GPS fix
taken standing at the booth, and the pavilion coordinate a booth named after
that pavilion borrows until someone surveys it. They differ by 30-50m, which
is the difference between "nearest booth" being right and being confidently
wrong at the six-kiosk cluster on the World Celebration walkway. Storing
which one a row holds lets a client say "about 200 ft, approximate" instead
of inventing precision it does not have.

Existing rows are backfilled to 'surveyed' only where a coordinate already
exists - there are none today, but a database that was hand-edited would
otherwise end up with coordinates of unstated provenance.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4f7b2c68e91'
down_revision = 'c3e6a91b8d52'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('booths', sa.Column('location_precision', sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE booths
        SET location_precision = 'surveyed'
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column('booths', 'location_precision')
