"""Email verification and persistent sending limits; no users auto-verified."""

import sqlalchemy as sa
from alembic import op

revision = "0008_email_verification"
down_revision = "0007_ai_quota"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("users", sa.Column("verification_digest", sa.String(64)))
    for name in (
        "verification_expires_at",
        "verification_sent_at",
        "verification_window_start",
    ):
        op.add_column("users", sa.Column(name, sa.DateTime(timezone=True)))
    for name in ("verification_attempts", "verification_send_count"):
        op.add_column(
            "users", sa.Column(name, sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "email_delivery_budget",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("sent", sa.Integer(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        sa.text(
            "INSERT INTO email_delivery_budget (id, day, sent) "
            "VALUES ('global', '2000-01-01', 0)"
        )
    )


def downgrade():
    op.drop_table("email_delivery_budget")
    for name in (
        "verification_send_count",
        "verification_attempts",
        "verification_window_start",
        "verification_sent_at",
        "verification_expires_at",
        "verification_digest",
        "email_verified",
    ):
        op.drop_column("users", name)
