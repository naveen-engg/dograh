"""Add user roles and support audit logs table

Revision ID: e1a2b3c4d5e6
Revises: 3a7b91c5d402
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e1a2b3c4d5e6"
down_revision = "3a7b91c5d402"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add role column to users table with default 'tenant_user'
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(),
            nullable=False,
            server_default="tenant_user",
        ),
    )

    # 2. Backfill existing superusers to 'super_admin'
    op.execute("UPDATE users SET role = 'super_admin' WHERE is_superuser = true")

    # 3. Create support_audit_logs table
    op.create_table(
        "support_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_email", sa.String(), nullable=True),
        sa.Column("target_organization_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("path", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column(
            "extra_metadata",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_organization_id"],
            ["organizations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 4. Create indexes
    op.create_index(
        "ix_support_audit_logs_actor_user_id",
        "support_audit_logs",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_audit_logs_target_organization_id",
        "support_audit_logs",
        ["target_organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_audit_logs_target_user_id",
        "support_audit_logs",
        ["target_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_audit_logs_created_at",
        "support_audit_logs",
        ["created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_support_audit_logs_created_at", table_name="support_audit_logs"
    )
    op.drop_index(
        "ix_support_audit_logs_target_user_id", table_name="support_audit_logs"
    )
    op.drop_index(
        "ix_support_audit_logs_target_organization_id",
        table_name="support_audit_logs",
    )
    op.drop_index(
        "ix_support_audit_logs_actor_user_id", table_name="support_audit_logs"
    )
    op.drop_table("support_audit_logs")
    op.drop_column("users", "role")
