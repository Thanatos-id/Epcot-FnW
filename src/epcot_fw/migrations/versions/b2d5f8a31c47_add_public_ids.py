"""add stable public_id to booths and menu_items

Revision ID: b2d5f8a31c47
Revises: a1c4e7d92f10
Create Date: 2026-08-09 15:05:00.000000

Clients (an iOS app's favourites, deep links, offline caches) need a handle
that outlives a rename or a rebuild. `id` is an autoincrement that renumbers
and `slug` is derived from a name sources revise mid-season, so neither is
safe to store outside this database.

Backfilled before the NOT NULL is applied so existing rows keep working.
gen_random_uuid() is built into PostgreSQL 13+; no extension required.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'b2d5f8a31c47'
down_revision = 'a1c4e7d92f10'
branch_labels = None
depends_on = None

_TABLES = ("booths", "menu_items")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "public_id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=True,
            ),
        )
        # Existing rows were added before the default existed.
        op.execute(f"UPDATE {table} SET public_id = gen_random_uuid() WHERE public_id IS NULL")
        op.alter_column(table, "public_id", nullable=False)
        op.create_unique_constraint(f"uq_{table}_public_id", table, ["public_id"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_constraint(f"uq_{table}_public_id", table, type_="unique")
        op.drop_column(table, "public_id")
