"""add booths.opens_at

Revision ID: f1a4c9d82e37
Revises: e5a8c3d71b24
Create Date: 2026-09-02 10:00:00.000000

Several booths run on a staggered schedule - the crawl has been seeing (and, in
sources/disney_food_blog.py's `_OPENING_SUFFIX_RE`, deliberately stripping) headings like
"The Alps - Opening October 2nd" and "The Wedge - NEW! Open September 18th through November 8th"
since before this column existed. That text told a person reading the source when a booth starts
serving; nothing captured it as data, so a guest standing at an unopened kiosk got the same "here's
the menu" screen as everywhere else.

No crawled source publishes this in a form worth trusting (the heading text is prose, not a
field), so it is curated-only from the start, the same as a booth's coordinates: staged through
docs/studio.html into data/manual/booth_locations.json, at the `manual` source's priority_rank 0,
which is what makes a correction here survive the next crawl rather than being overwritten by it.

Nullable, no backfill. NULL means "open now" - the case every booth was in before this column
existed, and the case that should need no action from anyone curating today's already-running
festival.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f1a4c9d82e37'
down_revision = 'e5a8c3d71b24'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('booths', sa.Column('opens_at', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('booths', 'opens_at')
