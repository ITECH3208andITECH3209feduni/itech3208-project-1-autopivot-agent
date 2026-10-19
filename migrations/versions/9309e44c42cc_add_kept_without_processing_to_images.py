"""Let a photograph be kept as-is, permanently exempt from the pipeline"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '9309e44c42cc'
down_revision: Union[str, Sequence[str], None] = 'f8d91a6b20e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'images',
        sa.Column(
            'kept_without_processing',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('images', 'kept_without_processing')
