"""add dietary_tags.kind and menu_items.alcohol_kind

Revision ID: a9c2e5b73f84
Revises: c7d3e918f4a2
Create Date: 2026-10-17 18:40:00.000000

Two new ways to narrow a menu, for the filtering the app is growing.

**`dietary_tags.kind`.** Sweet and savoury are tags in every structural sense
- a dish can be both (salted caramel pork, sweet-and-sour anything), neither
(most beers), and the list will grow to sour or bitter before long - so they
reuse the tag table and its M2M rather than earning columns of their own.
What they are not is dietary. `kind` is what keeps the two vocabularies
apart in one table: 'dietary' for the seven that were already here, 'flavour'
for the new ones.

That separation is load-bearing at the API, not just tidiness. The shipped
app builds its filter chips from whatever codes it finds in `dietary_tags`
and files anything outside its own inclusion list under "Hide items with".
Dropping sweet into that field would have put a "sweet" chip in every
installed copy's allergen filter, reading as something to avoid, before
anyone had written the UI meant to show it. So the feed splits them:
`dietary_tags` keeps carrying exactly what it carried, and flavours travel
in their own field.

**`menu_items.alcohol_kind`.** beer | wine | liquor | cider, null for
anything that is not an alcoholic drink. A sub-category rather than a tag,
because a drink is exactly one of them. Cider is its own value rather than
folded into beer: eleven of them are on this menu, and somebody filtering
for beer is not asking for an apple crumble cider, whoever brewed it.

Both nullable, no backfill. The crawl fills them in on the next parse, and
docs/studio.html is where anything it cannot read gets set by hand.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a9c2e5b73f84'
down_revision = 'c7d3e918f4a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'dietary_tags',
        sa.Column('kind', sa.Text(), nullable=False, server_default='dietary'),
    )
    op.add_column('menu_items', sa.Column('alcohol_kind', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('menu_items', 'alcohol_kind')
    op.drop_column('dietary_tags', 'kind')
