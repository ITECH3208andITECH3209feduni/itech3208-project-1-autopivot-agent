"""add backdrops library and dealership location"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b3c7d1a95e42'
down_revision: Union[str, Sequence[str], None] = 'f47ee772826e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'dealerships',
        sa.Column('location', sa.String(length=120), nullable=True),
    )

    op.create_table(
        'backdrops',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('dealership_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('storage_path', sa.String(length=1000), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column(
            'suits_angles',
            postgresql.ARRAY(sa.Text()),
            server_default='{}',
            nullable=False,
        ),
        sa.Column(
            'is_default', sa.Boolean(), server_default='false', nullable=False
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            'length(trim(name)) > 0', name=op.f('ck_backdrops_name_not_blank')
        ),
        sa.CheckConstraint(
            'length(trim(storage_path)) > 0',
            name=op.f('ck_backdrops_storage_path_not_blank'),
        ),
        sa.CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name=op.f('ck_backdrops_mime_type_allowed'),
        ),
        sa.ForeignKeyConstraint(
            ['dealership_id'],
            ['dealerships.id'],
            name=op.f('fk_backdrops_dealership_id_dealerships'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_backdrops')),
        sa.UniqueConstraint('id', 'dealership_id', name='backdrop_dealership_pair'),
        sa.UniqueConstraint(
            'dealership_id', 'name', name='backdrop_name_per_dealership'
        ),
    )
    op.create_index(
        op.f('ix_backdrops_dealership_id'), 'backdrops', ['dealership_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_backdrops_dealership_id'), table_name='backdrops')
    op.drop_table('backdrops')
    op.drop_column('dealerships', 'location')

