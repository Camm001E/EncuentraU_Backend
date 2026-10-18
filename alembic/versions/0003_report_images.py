"""Private primary photographs; existing reports keep a nullable relationship.

Revision ID: 0003_report_images
Revises: 0002_match_updated_at
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_report_images"
down_revision = "0002_match_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(100), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["report_id"], ["object_reports.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("report_id"),
        sa.UniqueConstraint("storage_key"),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name=op.f("ck_report_images_content_type"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0", name=op.f("ck_report_images_positive_size")
        ),
        sa.CheckConstraint(
            "width BETWEEN 1 AND 4096 AND height BETWEEN 1 AND 4096",
            name=op.f("ck_report_images_dimensions"),
        ),
        sa.CheckConstraint(
            "length(sha256) = 64", name=op.f("ck_report_images_sha256_length")
        ),
    )


def downgrade() -> None:
    op.drop_table("report_images")
