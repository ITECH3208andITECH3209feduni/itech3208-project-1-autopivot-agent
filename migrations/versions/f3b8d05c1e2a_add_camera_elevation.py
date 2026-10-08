"""Record where the camera was when the source photograph was taken"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f3b8d05c1e2a'
down_revision: Union[str, Sequence[str], None] = 'e1a4f6b2c907'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ELEVATION_CONSTRAINT = 'ck_processing_jobs_camera_elevation_range'
CONFIDENCE_CONSTRAINT = 'ck_processing_jobs_elevation_confidence_range'
METHOD_CONSTRAINT = 'ck_processing_jobs_elevation_method_allowed'


def upgrade() -> None:
    op.add_column(
        'processing_jobs',
        sa.Column('camera_elevation_deg', sa.Numeric(4, 2), nullable=True),
    )
    op.add_column(
        'processing_jobs',
        sa.Column('elevation_confidence', sa.Numeric(4, 3), nullable=True),
    )
    op.add_column(
        'processing_jobs',
        sa.Column('elevation_method', sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        op.f(ELEVATION_CONSTRAINT),
        'processing_jobs',
        'camera_elevation_deg IS NULL OR camera_elevation_deg BETWEEN -5 AND 35',
    )
    op.create_check_constraint(
        op.f(CONFIDENCE_CONSTRAINT),
        'processing_jobs',
        'elevation_confidence IS NULL OR elevation_confidence BETWEEN 0 AND 1',
    )
    op.create_check_constraint(
        op.f(METHOD_CONSTRAINT),
        'processing_jobs',
        "elevation_method IS NULL OR elevation_method IN "
        "('wheel_ellipse', 'roof_underside', 'shot_angle', 'assumed')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(METHOD_CONSTRAINT), 'processing_jobs', type_='check')
    op.drop_constraint(op.f(CONFIDENCE_CONSTRAINT), 'processing_jobs', type_='check')
    op.drop_constraint(op.f(ELEVATION_CONSTRAINT), 'processing_jobs', type_='check')
    op.drop_column('processing_jobs', 'elevation_method')
    op.drop_column('processing_jobs', 'elevation_confidence')
    op.drop_column('processing_jobs', 'camera_elevation_deg')

