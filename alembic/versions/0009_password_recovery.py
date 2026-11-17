"""Separate recovery codes and session revocation; preserves all existing accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0009_password_recovery"
down_revision = "0008_email_verification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("recovery_digest", sa.String(64)))
    for name in ("recovery_expires_at", "recovery_sent_at", "recovery_window_start"):
        op.add_column("users", sa.Column(name, sa.DateTime(timezone=True)))
    for name in ("recovery_attempts", "recovery_send_count", "session_version"):
        op.add_column(
            "users", sa.Column(name, sa.Integer(), nullable=False, server_default="0")
        )


def downgrade():
    for name in (
        "session_version",
        "recovery_send_count",
        "recovery_attempts",
        "recovery_window_start",
        "recovery_sent_at",
        "recovery_expires_at",
        "recovery_digest",
    ):
        op.drop_column("users", name)
