"""drop reviews table

Revision ID: c3e6a91b8d52
Revises: b2d5f8a31c47
Create Date: 2026-08-21 23:40:00.000000

The mined-review feature is being retired. It only ever had one supplier
(AllEars, which now returns 403 to us anyway), the ratings were attached by
scanning free-text for booth-name mentions rather than by the reviewer
naming a booth, and a rating derived that loosely is not something to rank
an app's recommendations on. When ratings come back it will be as a first-
party system with its own shape, so there is nothing here worth keeping.

The downgrade recreates the table empty. Restoring the rows themselves is a
restore-from-backup job, not a migration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3e6a91b8d52'
down_revision = 'b2d5f8a31c47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Staged review records outlive the table they fed. 'review' is no longer
    # a valid entity_type, so leaving them staged means every future resolve
    # pass walks rows nothing will ever claim. Provenance rows go first only
    # to satisfy the foreign key - the review pass wrote straight to `reviews`
    # and never produced any, so this should delete nothing.
    op.execute(
        """
        DELETE FROM entity_field_provenance
        WHERE extracted_record_id IN (
            SELECT id FROM extracted_records WHERE entity_type = 'review'
        )
        """
    )
    op.execute("DELETE FROM extracted_records WHERE entity_type = 'review'")

    op.drop_index('ix_reviews_entity', table_name='reviews')
    op.drop_table('reviews')


def downgrade() -> None:
    op.create_table(
        'reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('external_review_id', sa.Text(), nullable=True),
        sa.Column('reviewer_name', sa.Text(), nullable=True),
        sa.Column('rating', sa.Numeric(precision=2, scale=1), nullable=False),
        sa.Column('rating_raw', sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column('recommended', sa.Boolean(), nullable=True),
        sa.Column('review_text', sa.Text(), nullable=True),
        sa.Column('review_url', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.Date(), nullable=True),
        sa.Column('match_method', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'entity_type',
            'entity_id',
            'source_id',
            'external_review_id',
            name='uq_reviews_entity_source_external',
        ),
    )
    op.create_index('ix_reviews_entity', 'reviews', ['entity_type', 'entity_id'], unique=False)
