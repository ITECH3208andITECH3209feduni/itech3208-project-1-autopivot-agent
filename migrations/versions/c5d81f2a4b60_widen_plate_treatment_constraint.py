"""Widen the plate_treatment check constraint

The pipeline used to record the category of what it did to a plate ('masked').
It now records the method — 'blur', 'pixelate' or 'white' — which the existing
constraint rejected, failing the job after the image had already been produced.

'masked' stays allowed: rows written before this change hold it, and dropping it
would make them invalid.

Revision ID: c5d81f2a4b60
Revises: a92e0e36bda3
Create Date: 2026-08-12

"""

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
    op.drop_constraint(CONSTRAINT, TABLE, type_='check')
    op.create_check_constraint(CONSTRAINT, TABLE, NEW)


def downgrade() -> None:
    # Rows holding a value the old constraint forbids would make it impossible
    # to re-add, so they are folded back to the category they belong to.
    op.execute(
        "UPDATE processing_jobs SET plate_treatment = 'masked' "
        "WHERE plate_treatment IN ('blur', 'pixelate', 'white')"
    )
    op.drop_constraint(CONSTRAINT, TABLE, type_='check')
    op.create_check_constraint(CONSTRAINT, TABLE, OLD)
