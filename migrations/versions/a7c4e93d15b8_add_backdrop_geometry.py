"""Record where the floor and the horizon are in a dealer's own backdrop"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7c4e93d15b8'
down_revision: Union[str, Sequence[str], None] = 'f3b8d05c1e2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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

