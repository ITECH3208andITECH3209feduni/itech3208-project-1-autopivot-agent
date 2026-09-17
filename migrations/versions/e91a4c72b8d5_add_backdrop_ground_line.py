"""Let a custom backdrop expose its own measured ground line

Every dealership-uploaded backdrop shared one hardcoded guess for where the
floor is (DEALER_BACKDROP.ground_y_ratio = 0.84 in compositing.py), regardless
of what the scene actually looks like. Any backdrop whose horizon sits
somewhere else got a vehicle that floats above the floor or sinks below it.
This column lets a backdrop record its own measured ratio; NULL keeps the old
guessed behaviour so nothing breaks for a backdrop nobody has tuned yet
(APA-138).

Revision ID: e91a4c72b8d5
Revises: d7e2c9a13f84
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e91a4c72b8d5'
down_revision: Union[str, Sequence[str], None] = 'd7e2c9a13f84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GROUND_RATIO_CONSTRAINT = 'ck_backdrops_ground_y_ratio_plausible'


def upgrade() -> None:
    op.add_column('backdrops', sa.Column('ground_y_ratio', sa.Float(), nullable=True))
    op.create_check_constraint(
        op.f(GROUND_RATIO_CONSTRAINT),
        'backdrops',
        "ground_y_ratio IS NULL OR ground_y_ratio BETWEEN 0.05 AND 0.98",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(GROUND_RATIO_CONSTRAINT), 'backdrops', type_='check')
    op.drop_column('backdrops', 'ground_y_ratio')
