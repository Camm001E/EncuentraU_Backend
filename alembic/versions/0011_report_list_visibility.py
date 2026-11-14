"""Allow closed reports to leave lists without losing conversation context."""

import sqlalchemy as sa
from alembic import op

revision = "0011_report_list_visibility"
down_revision = "0010_match_visual_review"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "object_reports",
        sa.Column(
            "hidden_from_lists", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(
            "hidden_closed_only",
            "object_reports",
            "NOT hidden_from_lists OR status <> 'active'",
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("hidden_closed_only", "object_reports", type_="check")
    op.drop_column("object_reports", "hidden_from_lists")
