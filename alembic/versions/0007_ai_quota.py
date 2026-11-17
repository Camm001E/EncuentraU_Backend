"""Persistent AI allowance counters; independent of Redis and process restarts."""

import sqlalchemy as sa
from alembic import op

revision = "0007_ai_quota"
down_revision = "0006_match_scoring_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_quota_counters",
        sa.Column("scope", sa.String(80), primary_key=True),
        sa.Column("bucket", sa.String(40), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("used >= 0", name="ck_ai_quota_nonnegative"),
    )
    op.create_index("ix_ai_quota_expiry", "ai_quota_counters", ["expires_at"])


def downgrade():
    op.drop_table("ai_quota_counters")
