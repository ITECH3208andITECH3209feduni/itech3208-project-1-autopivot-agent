"""Record where the floor and the horizon are in a dealer's own backdrop

A dealership's backdrop was composited against a ground line assumed to be 84%
of the way down the canvas. That is correct for the two studio scenes, which
were measured by hand, and a guess for every photograph a dealer uploads: a
showroom whose floor meets the wall higher than that leaves the vehicle sunk
into the concrete, and one whose floor sits lower leaves it hovering above it.

The geometry is now measured from the image itself when it is uploaded, by
`backdrop_analysis.py`, and kept here so it is measured once rather than on
every job. `horizon_y_ratio` is the half of Phase 1 that cannot be recovered
from the vehicle photograph — `elevation.py` estimates where the camera was for
one photograph, and this says where the eye level falls in the scene it is about
to be placed into.

Every column is nullable. A backdrop uploaded before this migration has never
been measured, which is a different state from having been measured and found
unreadable: a seamless white cyclorama has no lines in it to converge on and is
recorded with method 'assumed' and a zero confidence. The compositor treats
those two cases differently, so the schema has to be able to express both.

Revision ID: a7c4e93d15b8
Revises: f3b8d05c1e2a
Create Date: 2026-08-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7c4e93d15b8'
down_revision: Union[str, Sequence[str], None] = 'f3b8d05c1e2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Passed through op.f() at each call site; a bare, already-prefixed name is run
# through the metadata naming convention a second time, which is what broke
# c5d81f2a4b60 on a clean database.
HORIZON_RATIO_CONSTRAINT = 'ck_backdrops_horizon_y_ratio_range'
HORIZON_CONFIDENCE_CONSTRAINT = 'ck_backdrops_horizon_confidence_range'
HORIZON_METHOD_CONSTRAINT = 'ck_backdrops_horizon_method_allowed'
FLOOR_RATIO_CONSTRAINT = 'ck_backdrops_floor_top_y_ratio_range'
FLOOR_CONFIDENCE_CONSTRAINT = 'ck_backdrops_floor_confidence_range'
ELEVATION_CONSTRAINT = 'ck_backdrops_camera_elevation_range'


def upgrade() -> None:
    op.add_column('backdrops', sa.Column('horizon_y_ratio', sa.Numeric(4, 3), nullable=True))
    op.add_column('backdrops', sa.Column('horizon_confidence', sa.Numeric(4, 3), nullable=True))
    op.add_column('backdrops', sa.Column('horizon_method', sa.String(length=20), nullable=True))
    op.add_column('backdrops', sa.Column('floor_top_y_ratio', sa.Numeric(4, 3), nullable=True))
    op.add_column('backdrops', sa.Column('floor_confidence', sa.Numeric(4, 3), nullable=True))
    op.add_column('backdrops', sa.Column('camera_elevation_deg', sa.Numeric(5, 2), nullable=True))
    # NOT NULL with a server default, so the rows that already exist take the
    # honest value: nobody has corrected them, because there was nothing to
    # correct until now.
    op.add_column(
        'backdrops',
        sa.Column(
            'geometry_overridden',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_check_constraint(
        op.f(HORIZON_RATIO_CONSTRAINT),
        'backdrops',
        'horizon_y_ratio IS NULL OR horizon_y_ratio BETWEEN 0 AND 1',
    )
    op.create_check_constraint(
        op.f(HORIZON_CONFIDENCE_CONSTRAINT),
        'backdrops',
        'horizon_confidence IS NULL OR horizon_confidence BETWEEN 0 AND 1',
    )
    op.create_check_constraint(
        op.f(HORIZON_METHOD_CONSTRAINT),
        'backdrops',
        "horizon_method IS NULL OR "
        "horizon_method IN ('vanishing_point', 'floor_junction', 'assumed')",
    )
    op.create_check_constraint(
        op.f(FLOOR_RATIO_CONSTRAINT),
        'backdrops',
        'floor_top_y_ratio IS NULL OR floor_top_y_ratio BETWEEN 0 AND 1',
    )
    op.create_check_constraint(
        op.f(FLOOR_CONFIDENCE_CONSTRAINT),
        'backdrops',
        'floor_confidence IS NULL OR floor_confidence BETWEEN 0 AND 1',
    )
    op.create_check_constraint(
        op.f(ELEVATION_CONSTRAINT),
        'backdrops',
        'camera_elevation_deg IS NULL OR camera_elevation_deg BETWEEN -90 AND 90',
    )


def downgrade() -> None:
    op.drop_constraint(op.f(ELEVATION_CONSTRAINT), 'backdrops', type_='check')
    op.drop_constraint(op.f(FLOOR_CONFIDENCE_CONSTRAINT), 'backdrops', type_='check')
    op.drop_constraint(op.f(FLOOR_RATIO_CONSTRAINT), 'backdrops', type_='check')
    op.drop_constraint(op.f(HORIZON_METHOD_CONSTRAINT), 'backdrops', type_='check')
    op.drop_constraint(op.f(HORIZON_CONFIDENCE_CONSTRAINT), 'backdrops', type_='check')
    op.drop_constraint(op.f(HORIZON_RATIO_CONSTRAINT), 'backdrops', type_='check')

    op.drop_column('backdrops', 'geometry_overridden')
    op.drop_column('backdrops', 'camera_elevation_deg')
    op.drop_column('backdrops', 'floor_confidence')
    op.drop_column('backdrops', 'floor_top_y_ratio')
    op.drop_column('backdrops', 'horizon_method')
    op.drop_column('backdrops', 'horizon_confidence')
    op.drop_column('backdrops', 'horizon_y_ratio')
