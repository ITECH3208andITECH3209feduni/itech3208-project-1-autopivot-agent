"""Record what a photograph is of, not just its role

A URL import pulls in whatever the listing page published — advertisement
banners, dealer badges, safety-rating graphics, interior shots — alongside the
vehicle. Only an exterior shot can be composited onto a backdrop, so the
classifier's verdict is stored against the image and the rest of the
application can act on it.

Revision ID: d7e2c9a13f84
Revises: c5d81f2a4b60
Create Date: 2026-08-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd7e2c9a13f84'
down_revision: Union[str, Sequence[str], None] = 'c5d81f2a4b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Passed through op.f() at each call site; a bare, already-prefixed name is run
# through the metadata naming convention a second time.
KIND_CONSTRAINT = 'ck_images_image_kind_allowed'
CONFIDENCE_CONSTRAINT = 'ck_images_kind_confidence_range'


def upgrade() -> None:
    op.add_column('images', sa.Column('image_kind', sa.String(length=20), nullable=True))
    op.add_column('images', sa.Column('kind_confidence', sa.Numeric(4, 3), nullable=True))
    op.create_check_constraint(
        op.f(KIND_CONSTRAINT),
        'images',
        "image_kind IS NULL OR image_kind IN "
        "('exterior', 'interior', 'detail', 'advertisement', 'unknown')",
    )
    op.create_check_constraint(
        op.f(CONFIDENCE_CONSTRAINT),
        'images',
        "kind_confidence IS NULL OR kind_confidence BETWEEN 0 AND 1",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(CONFIDENCE_CONSTRAINT), 'images', type_='check')
    op.drop_constraint(op.f(KIND_CONSTRAINT), 'images', type_='check')
    op.drop_column('images', 'kind_confidence')
    op.drop_column('images', 'image_kind')
