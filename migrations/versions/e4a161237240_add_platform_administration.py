"""add platform administration fields and audit log

Revision ID: e4a161237240
Revises: d7e2c9a13f84
Create Date: 2026-09-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a161237240"
down_revision: Union[str, Sequence[str], None] = "d7e2c9a13f84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dealerships", sa.Column("contact_name", sa.String(length=200), nullable=True))
    op.add_column("dealerships", sa.Column("contact_email", sa.String(length=320), nullable=True))
    op.add_column("dealerships", sa.Column("contact_phone", sa.String(length=50), nullable=True))
    op.create_index(
        "uq_dealerships_name_lower",
        "dealerships",
        [sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("dealership_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("request_path", sa.String(length=500), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'denied', 'failed')",
            name=op.f("ck_audit_logs_outcome_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dealership_id"],
            ["dealerships.id"],
            name=op.f("fk_audit_logs_dealership_id_dealerships"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_actor_user_id"), "audit_logs", ["actor_user_id"])
    op.create_index(op.f("ix_audit_logs_dealership_id"), "audit_logs", ["dealership_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_dealership_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_user_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("uq_dealerships_name_lower", table_name="dealerships")
    op.drop_column("dealerships", "contact_phone")
    op.drop_column("dealerships", "contact_email")
    op.drop_column("dealerships", "contact_name")
