"""Persist photo comparisons independently of matching scores."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_match_visual_review"
down_revision = "0009_password_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "object_matches",
        sa.Column(
            "visual_review",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("object_matches", "visual_review")
