"""Trace a processed photograph back to the original it was made from

Every claim the realism work makes is settled by a before-and-after pair: the
dealer's own photograph beside the composite produced from it. Nothing recorded
which was which. The only link was the processing job that happened to produce
the output, and a job is deleted the moment its input photograph is, so the
pairing vanished exactly when someone wanted to look back at it.

The reference is a pair — (source_image_id, vehicle_listing_id) against
(id, vehicle_listing_id) — for the same reason the processing_jobs references
are. A composite key cannot be satisfied by a row belonging to another
dealership's listing, so a derived image is confined to the listing it came
from by the database rather than by whoever wrote the query.

RESTRICT matches every neighbouring constraint. The alternatives both lose the
pair without saying so: CASCADE would take the processed result away with the
original, and SET NULL would leave an "after" that can no longer be shown beside
anything. Deletion instead clears the dependent rows deliberately and in order,
in api/routes_listings.py.

Existing rows keep NULL, which is the truthful value: originals never had a
source, and for processed rows written before today there is nothing left to
reconstruct the pairing from.

Revision ID: e1a4f6b2c907
Revises: d7e2c9a13f84
Create Date: 2026-08-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e1a4f6b2c907'
down_revision: Union[str, Sequence[str], None] = 'd7e2c9a13f84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Passed through op.f() at each call site; a bare, already-prefixed name is run
# through the metadata naming convention a second time.
SOURCE_CONSTRAINT = 'source_image_same_listing'
NOT_SELF_CONSTRAINT = 'ck_images_source_image_not_self'
SOURCE_INDEX = 'ix_images_source_image_id'


def upgrade() -> None:
    op.add_column('images', sa.Column('source_image_id', sa.BigInteger(), nullable=True))
    # Before the constraint, not after it: PostgreSQL indexes a referencing
    # column for nobody, and the RESTRICT check below has to look for children
    # every time a photograph is deleted. Unindexed that is a sequential scan of
    # images on each delete.
    op.create_index(op.f(SOURCE_INDEX), 'images', ['source_image_id'], unique=False)
    op.create_foreign_key(
        op.f(SOURCE_CONSTRAINT),
        'images',
        'images',
        ['source_image_id', 'vehicle_listing_id'],
        ['id', 'vehicle_listing_id'],
        ondelete='RESTRICT',
    )
    # A row naming itself as its own source could never be deleted: RESTRICT is
    # checked against the row being removed too, so its own reference would
    # refuse the delete and leave the dealer stuck with the photograph.
    op.create_check_constraint(
        op.f(NOT_SELF_CONSTRAINT),
        'images',
        'source_image_id IS NULL OR source_image_id <> id',
    )


def downgrade() -> None:
    op.drop_constraint(op.f(NOT_SELF_CONSTRAINT), 'images', type_='check')
    op.drop_constraint(op.f(SOURCE_CONSTRAINT), 'images', type_='foreignkey')
    op.drop_index(op.f(SOURCE_INDEX), table_name='images')
    op.drop_column('images', 'source_image_id')
