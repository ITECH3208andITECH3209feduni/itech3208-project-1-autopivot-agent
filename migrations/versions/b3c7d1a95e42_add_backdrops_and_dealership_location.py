"""add backdrops library and dealership location

Backdrops are owned per dealership rather than shared globally, so a dealership
can rename or remove its own copies without affecting anyone else. Keeping
dealership_id NOT NULL is also what lets a later composite foreign key from
processing_jobs enforce tenant isolation in the database — PostgreSQL skips
composite foreign key checks entirely when any column in them is NULL, so a
nullable "global backdrop" column would silently disable that protection.

Revision ID: b3c7d1a95e42
Revises: f47ee772826e
Create Date: 2026-08-09 18:02:11.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
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
        # An empty array means the backdrop suits all angles. The angle
        # vocabulary is intentionally unconstrained: how angles get determined
        # is still an open decision, and a CHECK written now would only have to
        # be migrated away later.
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
        # Target of the composite foreign key that processing_jobs will use.
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
