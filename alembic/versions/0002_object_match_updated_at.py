"""Track recalculation time without replacing existing matches.

Revision ID: 0002_match_updated_at
Revises: 0001_postgresql_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_match_updated_at"
down_revision: str | None = "0001_postgresql_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "object_matches",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(sa.text("UPDATE object_matches SET updated_at = created_at"))


def downgrade() -> None:
    op.drop_column("object_matches", "updated_at")
