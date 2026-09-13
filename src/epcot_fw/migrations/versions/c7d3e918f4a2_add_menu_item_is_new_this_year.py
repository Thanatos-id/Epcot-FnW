"""add menu_items.is_new_this_year

Revision ID: c7d3e918f4a2
Revises: f1a4c9d82e37
Create Date: 2026-09-12 14:20:00.000000

Every season the sources mark which dishes are new to the festival, and every
season that mark has been thrown away: it arrives as "(New)" after a name or
"NEW!" in front of one, and a name is prose, so the marker travelled as prose
and stopped at the canonical layer. 317 of the extracted records held when
this column was added carry one, across 129 distinct dishes, and not one of
them reached the feed the app reads.

Read at parse time now (normalize/newness.py), so it re-derives on every
crawl rather than being a one-off sweep - and correctable in
docs/studio.html like any other field, because a blog calling a returning
dish new is a mistake a person should be able to take back.

NOT NULL DEFAULT false, no backfill needed beyond `epcot-fw sources reparse`:
false is what every row already meant, and a source that says nothing about
newness is not claiming a dish is old. The flag needs no clearing between
seasons either - menu_items hang off a festival's booths, so next year's
festival brings its own rows and its own marks.

Deliberately not named `new`: that key is taken in the curated files, where
it means "the crawl never found this, create it rather than park it as a
merge conflict" - an entirely different fact about an entirely different
moment.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c7d3e918f4a2'
down_revision = 'f1a4c9d82e37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'menu_items',
        sa.Column('is_new_this_year', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('menu_items', 'is_new_this_year')
