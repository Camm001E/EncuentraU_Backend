"""Preserve legacy scoring provenance and version future recalculations.

Revision ID: 0006_match_scoring_version
Revises: 0005_delivery_closure
"""

import sqlalchemy as sa
from alembic import op

from app.domain.matching_version import (
    LEGACY_SCORING_VERSION,
    SCORING_VERSION_MAX_LENGTH,
)

revision = "0006_match_scoring_version"
down_revision = "0005_delivery_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An omitted version must never label an old/unknown writer as current.
    # The application explicitly supplies its current version on each proposal.
    op.add_column(
        "object_matches",
        sa.Column(
            "scoring_version",
            sa.String(SCORING_VERSION_MAX_LENGTH),
            nullable=False,
            server_default=LEGACY_SCORING_VERSION,
        ),
    )


def downgrade() -> None:
    op.drop_column("object_matches", "scoring_version")
