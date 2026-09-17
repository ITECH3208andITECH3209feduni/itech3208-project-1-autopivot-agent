"""add stock number, processing status and pipeline results

Three changes:

1. vehicle_listings gains stock_number ("STOCK #4471") and processing_status.
   processing_status is a separate axis to status: status is where the vehicle
   is in the sales cycle, processing_status is where its photographs are in the
   pipeline. A listing can be sold with images still awaiting review.

2. processing_jobs drops background_image_id and gains backdrop_id. The old
   composite key forced the background to be an image of the same listing,
   which made a reusable backdrop library impossible to express. Isolation is
   preserved by a denormalised dealership_id tied to both the listing and the
   backdrop, so a job can never reference another dealership's backdrop.

3. processing_jobs gains the per-image pipeline results the Results screen
   shows: detected angle and confidence, plate count and treatment, and a
   review state distinct from status, since a job can succeed and still need a
   human to look at it.

Revision ID: a92e0e36bda3
Revises: b3c7d1a95e42
Create Date: 2026-08-09 19:24:58.515955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a92e0e36bda3'
down_revision: Union[str, Sequence[str], None] = 'b3c7d1a95e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Reordered from autogenerate output, which grouped operations by table and
    # so created the foreign key onto vehicle_listings (id, dealership_id)
    # before the unique constraint that key requires. vehicle_listings is set up
    # first here for that reason.

    # ── vehicle_listings ──
    op.add_column('vehicle_listings', sa.Column('stock_number', sa.String(length=50), nullable=True))
    op.add_column('vehicle_listings', sa.Column('processing_status', sa.String(length=20), server_default='pending', nullable=False))
    # Must precede job_listing_same_dealership below.
    op.create_unique_constraint('listing_dealership_pair', 'vehicle_listings', ['id', 'dealership_id'])
    # NULL stock numbers stay unconstrained: PostgreSQL treats NULLs as distinct
    # in a unique index, so any number of listings may have none.
    op.create_unique_constraint('stock_number_per_dealership', 'vehicle_listings', ['dealership_id', 'stock_number'])
    op.create_check_constraint(op.f('ck_vehicle_listings_processing_status_allowed'), 'vehicle_listings', "processing_status IN ('pending', 'processing', 'complete', 'needs_review')")

    # ── processing_jobs ──
    # dealership_id is added nullable, backfilled from the owning listing, then
    # tightened. Adding it NOT NULL in one step — as autogenerate proposed —
    # would fail on any database that already has jobs in it.
    op.add_column('processing_jobs', sa.Column('dealership_id', sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE processing_jobs AS pj
           SET dealership_id = vl.dealership_id
          FROM vehicle_listings AS vl
         WHERE vl.id = pj.vehicle_listing_id
           AND pj.dealership_id IS NULL
        """
    )
    op.alter_column('processing_jobs', 'dealership_id', nullable=False)
    op.add_column('processing_jobs', sa.Column('backdrop_id', sa.BigInteger(), nullable=True))
    op.add_column('processing_jobs', sa.Column('detected_angle', sa.String(length=40), nullable=True))
    op.add_column('processing_jobs', sa.Column('angle_confidence', sa.Numeric(precision=4, scale=3), nullable=True))
    op.add_column('processing_jobs', sa.Column('plates_detected', sa.Integer(), nullable=True))
    op.add_column('processing_jobs', sa.Column('plate_treatment', sa.String(length=20), nullable=True))
    op.add_column('processing_jobs', sa.Column('review_state', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_processing_jobs_dealership_id'), 'processing_jobs', ['dealership_id'], unique=False)
    op.drop_constraint(op.f('background_image_same_listing'), 'processing_jobs', type_='foreignkey')
    op.create_foreign_key('job_listing_same_dealership', 'processing_jobs', 'vehicle_listings', ['vehicle_listing_id', 'dealership_id'], ['id', 'dealership_id'], ondelete='RESTRICT')
    op.create_foreign_key('backdrop_same_dealership', 'processing_jobs', 'backdrops', ['backdrop_id', 'dealership_id'], ['id', 'dealership_id'], ondelete='RESTRICT')
    op.create_check_constraint(op.f('ck_processing_jobs_angle_confidence_range'), 'processing_jobs', 'angle_confidence IS NULL OR angle_confidence BETWEEN 0 AND 1')
    op.create_check_constraint(op.f('ck_processing_jobs_plate_treatment_allowed'), 'processing_jobs', "plate_treatment IS NULL OR plate_treatment IN ('masked', 'overlay', 'none')")
    op.create_check_constraint(op.f('ck_processing_jobs_plates_detected_non_negative'), 'processing_jobs', 'plates_detected IS NULL OR plates_detected >= 0')
    op.create_check_constraint(op.f('ck_processing_jobs_review_state_allowed'), 'processing_jobs', "review_state IS NULL OR review_state IN ('ok', 'needs_review')")
    op.drop_column('processing_jobs', 'background_image_id')


def downgrade() -> None:
    """Downgrade schema."""
    # Mirror image of upgrade(): processing_jobs is dismantled first, so the
    # unique constraint its foreign key depends on is still present.
    op.add_column('processing_jobs', sa.Column('background_image_id', sa.BIGINT(), autoincrement=False, nullable=True))
    op.drop_constraint(op.f('ck_processing_jobs_review_state_allowed'), 'processing_jobs', type_='check')
    op.drop_constraint(op.f('ck_processing_jobs_plates_detected_non_negative'), 'processing_jobs', type_='check')
    op.drop_constraint(op.f('ck_processing_jobs_plate_treatment_allowed'), 'processing_jobs', type_='check')
    op.drop_constraint(op.f('ck_processing_jobs_angle_confidence_range'), 'processing_jobs', type_='check')
    op.drop_constraint('backdrop_same_dealership', 'processing_jobs', type_='foreignkey')
    op.drop_constraint('job_listing_same_dealership', 'processing_jobs', type_='foreignkey')
    op.create_foreign_key(op.f('background_image_same_listing'), 'processing_jobs', 'images', ['background_image_id', 'vehicle_listing_id'], ['id', 'vehicle_listing_id'], ondelete='RESTRICT')
    op.drop_index(op.f('ix_processing_jobs_dealership_id'), table_name='processing_jobs')
    op.drop_column('processing_jobs', 'review_state')
    op.drop_column('processing_jobs', 'plate_treatment')
    op.drop_column('processing_jobs', 'plates_detected')
    op.drop_column('processing_jobs', 'angle_confidence')
    op.drop_column('processing_jobs', 'detected_angle')
    op.drop_column('processing_jobs', 'backdrop_id')
    op.drop_column('processing_jobs', 'dealership_id')

    op.drop_constraint(op.f('ck_vehicle_listings_processing_status_allowed'), 'vehicle_listings', type_='check')
    op.drop_constraint('stock_number_per_dealership', 'vehicle_listings', type_='unique')
    op.drop_constraint('listing_dealership_pair', 'vehicle_listings', type_='unique')
    op.drop_column('vehicle_listings', 'processing_status')
    op.drop_column('vehicle_listings', 'stock_number')
