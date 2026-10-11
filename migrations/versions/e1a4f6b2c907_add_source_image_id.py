"""Trace a processed photograph back to the original it was made from"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e1a4f6b2c907'
down_revision: Union[str, Sequence[str], None] = 'd7e2c9a13f84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_CONSTRAINT = 'source_image_same_listing'
NOT_SELF_CONSTRAINT = 'ck_images_source_image_not_self'
SOURCE_INDEX = 'ix_images_source_image_id'


def upgrade() -> None:
    op.add_column('images', sa.Column('source_image_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f(SOURCE_INDEX), 'images', ['source_image_id'], unique=False)
    op.create_foreign_key(
        op.f(SOURCE_CONSTRAINT),
        'images',
        'images',
        ['source_image_id', 'vehicle_listing_id'],
        ['id', 'vehicle_listing_id'],
        ondelete='RESTRICT',
    )
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

