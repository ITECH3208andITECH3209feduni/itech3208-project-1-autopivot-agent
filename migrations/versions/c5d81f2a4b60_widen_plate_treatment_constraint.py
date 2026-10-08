"""Widen the plate_treatment check constraint"""

from typing import Sequence, Union

from alembic import op


revision: str = 'c5d81f2a4b60'
down_revision: Union[str, Sequence[str], None] = 'a92e0e36bda3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = 'ck_processing_jobs_plate_treatment_allowed'
TABLE = 'processing_jobs'

OLD = (
    "plate_treatment IS NULL OR "
    "plate_treatment IN ('masked', 'overlay', 'none')"
)
NEW = (
    "plate_treatment IS NULL OR "
    "plate_treatment IN ('masked', 'overlay', 'none', "
    "'blur', 'pixelate', 'white')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_='check')
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, NEW)


def downgrade() -> None:
    op.execute(
        "UPDATE processing_jobs SET plate_treatment = 'masked' "
        "WHERE plate_treatment IN ('blur', 'pixelate', 'white')"
    )
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_='check')
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, OLD)

