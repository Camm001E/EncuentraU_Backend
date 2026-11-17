"""ownership claims and authorized private conversations

Revision ID: 0004_ownership_chat
Revises: 0003_report_images
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ownership_chat"
down_revision: str | None = "0003_report_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ownership_claims",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("claimant_user_id", sa.Uuid(), nullable=False),
        sa.Column("custodian_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("ownership_evidence", sa.Text(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND admin_id IS NULL AND reviewed_at IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'approved' AND admin_id IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'rejected' AND admin_id IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) BETWEEN 3 AND 2000)",
            name=op.f("ck_ownership_claims_review_state"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_ownership_claims_status"),
        ),
        sa.CheckConstraint(
            "admin_note IS NULL OR length(admin_note) BETWEEN 1 AND 2000",
            name=op.f("ck_ownership_claims_note_length"),
        ),
        sa.CheckConstraint(
            "claimant_user_id <> custodian_user_id",
            name=op.f("ck_ownership_claims_different_users"),
        ),
        sa.CheckConstraint(
            "length(trim(ownership_evidence)) BETWEEN 10 AND 4000",
            name=op.f("ck_ownership_claims_evidence_length"),
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["users.id"],
            name=op.f("fk_ownership_claims_admin_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claimant_user_id"],
            ["users.id"],
            name=op.f("fk_ownership_claims_claimant_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["custodian_user_id"],
            ["users.id"],
            name=op.f("fk_ownership_claims_custodian_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["object_matches.id"],
            name=op.f("fk_ownership_claims_match_id_object_matches"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ownership_claims")),
        sa.UniqueConstraint("id", "match_id", name="uq_ownership_claims_id_match"),
        sa.UniqueConstraint("match_id", name=op.f("uq_ownership_claims_match_id")),
    )
    op.create_index(
        op.f("ix_ownership_claims_claimant_user_id"),
        "ownership_claims",
        ["claimant_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ownership_claims_created_at",
        "ownership_claims",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ownership_claims_custodian_user_id"),
        "ownership_claims",
        ["custodian_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ownership_claims_status_created_at",
        "ownership_claims",
        ["status", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "conversations",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'closed')", name=op.f("ck_conversations_status")
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "match_id"],
            ["ownership_claims.id", "ownership_claims.match_id"],
            name="fk_conversations_claim_match",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["object_matches.id"],
            name=op.f("fk_conversations_match_id_object_matches"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("claim_id", name=op.f("uq_conversations_claim_id")),
        sa.UniqueConstraint("match_id", name=op.f("uq_conversations_match_id")),
    )
    op.create_table(
        "conversation_participants",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_participants_conversation_id_conversations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_conversation_participants_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id", "user_id", name=op.f("pk_conversation_participants")
        ),
    )
    op.create_index(
        op.f("ix_conversation_participants_user_id"),
        "conversation_participants",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("client_message_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(body)) BETWEEN 1 AND 2000",
            name=op.f("ck_messages_body_length"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "sender_id"],
            [
                "conversation_participants.conversation_id",
                "conversation_participants.user_id",
            ],
            name="fk_messages_participant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["users.id"],
            name=op.f("fk_messages_sender_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "sender_id", "client_message_id", name="uq_messages_sender_client"
        ),
    )
    op.create_index(
        "ix_messages_conversation_created_id",
        "messages",
        ["conversation_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index(
        op.f("ix_conversation_participants_user_id"),
        table_name="conversation_participants",
    )
    op.drop_table("conversation_participants")
    op.drop_table("conversations")
    op.drop_index(
        "ix_ownership_claims_status_created_at", table_name="ownership_claims"
    )
    op.drop_index(
        op.f("ix_ownership_claims_custodian_user_id"), table_name="ownership_claims"
    )
    op.drop_index("ix_ownership_claims_created_at", table_name="ownership_claims")
    op.drop_index(
        op.f("ix_ownership_claims_claimant_user_id"), table_name="ownership_claims"
    )
    op.drop_table("ownership_claims")
