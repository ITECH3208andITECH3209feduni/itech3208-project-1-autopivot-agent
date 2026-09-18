"""Record where the camera was when the source photograph was taken

A dealer's photographs are taken by a person walking round a car on a lot:
crouching for the front three-quarter, standing for the side, phone held
overhead for the rear. Each of those has a different horizon, and the showroom
backdrop's horizon is fixed, so the floor behind the car recedes at the wrong
rate and the eye reads the composite as wrong however good the shadow is. The
estimator in elevation.py measures the camera height from the cutout alone;
these columns are where its answer is kept, so the alignment work that consumes
it can be checked against real jobs rather than asserted.

Three columns rather than one, because the number on its own is not usable.
The confidence is what lets a caller refuse to act on a weak estimate, and the
method names which of the four rungs produced it — a tyre actually measured, a
gap under the sills actually measured, a population prior over how dealers
shoot, or a flat assumption of standing eye level.

All three are nullable, and that is not only for the rows already in the table.
A job that stops before a cutout exists — an advertisement banner, or a
photograph with no vehicle in it — has nothing to estimate from and correctly
records nothing. What must not be confused with that case is a run where the
cascade fell all the way through to its last rung: it still writes a number,
with method 'assumed' and a low confidence, precisely so that "we guessed" can
be told apart from "nobody looked".

Revision ID: f3b8d05c1e2a
Revises: e1a4f6b2c907
Create Date: 2026-08-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f3b8d05c1e2a'
down_revision: Union[str, Sequence[str], None] = 'e1a4f6b2c907'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Passed through op.f() at each call site; a bare, already-prefixed name is run
# through the metadata naming convention a second time.
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
    # The bounds are elevation.MIN_ELEVATION_DEG and MAX_ELEVATION_DEG: below
    # them the photographer is kneeling under the wheel centres, above them they
    # are on a ladder or a drone, and neither is the case Phase 1 is built for.
    # A value outside the range means the estimator inverted a bad measurement,
    # which is worth refusing at the database rather than aligning a horizon to.
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
    # elevation.ELEVATION_METHODS. Constrained, where detected_angle is not,
    # because these four values name the rungs of one cascade in one module
    # rather than a vocabulary still being argued about.
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
