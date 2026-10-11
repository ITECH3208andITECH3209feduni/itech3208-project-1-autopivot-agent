"""Add user token version for immediate reset session revocation."""

from alembic import op
import sqlalchemy as sa

revision = "f8d91a6b20e4"
down_revision = "e4a161237240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "token_version")

