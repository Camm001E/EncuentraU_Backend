from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    or_,
    select,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.domain.matching_version import (
    CURRENT_SCORING_VERSION,
    LEGACY_SCORING_VERSION,
    SCORING_VERSION_MAX_LENGTH,
)
from app.infrastructure.database.base import Base

JSON_DATA = JSON().with_variant(JSONB(), "postgresql")


class UUIDPrimaryKey:
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        UniqueConstraint("student_code"),
        CheckConstraint("role IN ('student', 'admin')", name="role"),
    )

    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254))
    student_code: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(20), default="student", server_default="student"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )

    reports: Mapped[list[ObjectReport]] = relationship(
        back_populates="user", passive_deletes="all"
    )


class ObjectReport(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "object_reports"
    __table_args__ = (
        CheckConstraint("report_type IN ('lost', 'found')", name="report_type"),
        CheckConstraint("status IN ('active', 'resolved', 'cancelled')", name="status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    report_type: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )
    object_type: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    primary_color: Mapped[str | None] = mapped_column(String(100))
    secondary_colors: Mapped[list[str]] = mapped_column(
        JSON_DATA, default=list, server_default=text("'[]'")
    )
    brand: Mapped[str | None] = mapped_column(String(100))
    shape: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(300))
    event_date: Mapped[date] = mapped_column(Date)
    private_feature: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="reports")
    analyses: Mapped[list[ImageAnalysis]] = relationship(
        back_populates="report", cascade="all, delete-orphan", passive_deletes=True
    )
    image: Mapped[ReportImage | None] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    lost_matches: Mapped[list[ObjectMatch]] = relationship(
        back_populates="lost_report",
        foreign_keys="ObjectMatch.lost_report_id",
        passive_deletes="all",
    )
    found_matches: Mapped[list[ObjectMatch]] = relationship(
        back_populates="found_report",
        foreign_keys="ObjectMatch.found_report_id",
        passive_deletes="all",
    )


class ImageAnalysis(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "image_analyses"
    __table_args__ = (
        CheckConstraint("confidence IN ('baja', 'media', 'alta')", name="confidence"),
    )

    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_reports.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    extracted_data: Mapped[dict[str, Any]] = mapped_column(JSON_DATA)
    confidence: Mapped[str] = mapped_column(String(10))

    report: Mapped[ObjectReport] = relationship(back_populates="analyses")


class ReportImage(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "report_images"
    __table_args__ = (
        UniqueConstraint("report_id"),
        UniqueConstraint("storage_key"),
        CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="content_type",
        ),
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint(
            "width BETWEEN 1 AND 4096 AND height BETWEEN 1 AND 4096", name="dimensions"
        ),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
    )

    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_reports.id", ondelete="CASCADE")
    )
    storage_key: Mapped[str] = mapped_column(String(100))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    report: Mapped[ObjectReport] = relationship(back_populates="image")


class ObjectMatch(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "object_matches"
    __table_args__ = (
        UniqueConstraint(
            "lost_report_id", "found_report_id", name="uq_object_matches_pair"
        ),
        CheckConstraint("lost_report_id <> found_report_id", name="different_reports"),
        CheckConstraint("percentage BETWEEN 0 AND 100", name="percentage_range"),
        CheckConstraint("identity_percentage BETWEEN 0 AND 100", name="identity_range"),
        CheckConstraint("context_percentage BETWEEN 0 AND 100", name="context_range"),
        CheckConstraint("evidence_coverage BETWEEN 0 AND 100", name="coverage_range"),
        CheckConstraint("level IN ('high', 'possible', 'low')", name="level"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="status"),
        CheckConstraint(
            "compatible OR (percentage <= 29 AND level = 'low')", name="compatibility"
        ),
    )

    lost_report_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_reports.id", ondelete="CASCADE"), index=True
    )
    found_report_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_reports.id", ondelete="CASCADE"), index=True
    )
    percentage: Mapped[int] = mapped_column(SmallInteger)
    identity_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    context_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    evidence_coverage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    compatible: Mapped[bool] = mapped_column(Boolean)
    level: Mapped[str] = mapped_column(String(16))
    scoring_version: Mapped[str] = mapped_column(
        String(SCORING_VERSION_MAX_LENGTH),
        default=CURRENT_SCORING_VERSION,
        server_default=LEGACY_SCORING_VERSION,
    )
    factors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DATA, default=list, server_default=text("'[]'")
    )
    warnings: Mapped[list[str]] = mapped_column(
        JSON_DATA, default=list, server_default=text("'[]'")
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )

    lost_report: Mapped[ObjectReport] = relationship(
        back_populates="lost_matches", foreign_keys=[lost_report_id]
    )
    found_report: Mapped[ObjectReport] = relationship(
        back_populates="found_matches", foreign_keys=[found_report_id]
    )


class OwnershipClaim(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "ownership_claims"
    __table_args__ = (
        UniqueConstraint("match_id"),
        UniqueConstraint("id", "match_id", name="uq_ownership_claims_id_match"),
        CheckConstraint(
            "claimant_user_id <> custodian_user_id", name="different_users"
        ),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status"),
        CheckConstraint(
            "length(trim(ownership_evidence)) BETWEEN 10 AND 4000",
            name="evidence_length",
        ),
        CheckConstraint(
            "admin_note IS NULL OR length(admin_note) BETWEEN 1 AND 2000",
            name="note_length",
        ),
        CheckConstraint(
            "(status = 'pending' AND admin_id IS NULL AND reviewed_at IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'approved' AND admin_id IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND rejection_reason IS NULL) OR "
            "(status = 'rejected' AND admin_id IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) BETWEEN 3 AND 2000)",
            name="review_state",
        ),
        Index("ix_ownership_claims_status_created_at", "status", "created_at", "id"),
        Index("ix_ownership_claims_created_at", "created_at"),
    )
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_matches.id", ondelete="RESTRICT")
    )
    claimant_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    custodian_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )
    ownership_evidence: Mapped[str] = mapped_column(Text)
    admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    admin_note: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("match_id"),
        UniqueConstraint("claim_id"),
        ForeignKeyConstraint(
            ["claim_id", "match_id"],
            ["ownership_claims.id", "ownership_claims.match_id"],
            name="fk_conversations_claim_match",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('active', 'closed')", name="status"),
    )
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_matches.id", ondelete="RESTRICT")
    )
    claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active"
    )


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "sender_id"],
            [
                "conversation_participants.conversation_id",
                "conversation_participants.user_id",
            ],
            name="fk_messages_participant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "sender_id", "client_message_id", name="uq_messages_sender_client"
        ),
        CheckConstraint("length(trim(body)) BETWEEN 1 AND 2000", name="body_length"),
        Index(
            "ix_messages_conversation_created_id", "conversation_id", "created_at", "id"
        ),
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    sender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    client_message_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    body: Mapped[str] = mapped_column(Text)


class Delivery(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("match_id"),
        UniqueConstraint("claim_id"),
        UniqueConstraint("conversation_id"),
        ForeignKeyConstraint(
            ["claim_id", "match_id"],
            ["ownership_claims.id", "ownership_claims.match_id"],
            name="fk_deliveries_claim_match",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('coordinating', 'awaiting_confirmations', "
            "'awaiting_admin', 'disputed', 'completed')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'coordinating' AND claimant_confirmed_at IS NULL "
            "AND custodian_confirmed_at IS NULL) OR  "
            "(status = 'awaiting_confirmations' AND "
            "((claimant_confirmed_at IS NULL AND custodian_confirmed_at "
            "IS NOT NULL) OR (claimant_confirmed_at IS NOT NULL AND "
            "custodian_confirmed_at IS NULL))) OR  "
            "(status IN ('awaiting_admin', 'completed') AND "
            "claimant_confirmed_at IS NOT NULL AND custodian_confirmed_at "
            "IS NOT NULL) OR status = 'disputed'",
            name="confirmations",
        ),
        CheckConstraint(
            "(status = 'completed' AND admin_id IS NOT NULL AND "
            "completed_at IS NOT NULL) OR (status <> 'completed' AND "
            "completed_at IS NULL)",
            name="completion",
        ),
        CheckConstraint(
            "(status = 'disputed' AND dispute_raised_by_user_id IS NOT "
            "NULL AND dispute_reason IS NOT NULL AND "
            "length(trim(dispute_reason)) BETWEEN 10 AND 2000) OR (status "
            "<> 'disputed' AND dispute_raised_by_user_id IS NULL AND "
            "dispute_reason IS NULL)",
            name="dispute",
        ),
        CheckConstraint(
            "admin_note IS NULL OR length(trim(admin_note)) BETWEEN 1 AND 2000",
            name="note_length",
        ),
        Index("ix_deliveries_status_created_at", "status", "created_at", "id"),
        Index("ix_deliveries_created_at", "created_at"),
    )
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_matches.id", ondelete="RESTRICT")
    )
    claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(
        String(24), default="coordinating", server_default="coordinating"
    )
    claimant_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    custodian_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    dispute_raised_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    admin_note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryEvent(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "delivery_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('delivery_created', 'custodian_confirmed', "
            "'claimant_confirmed', 'dispute_opened', 'admin_reopened', "
            "'admin_completed')",
            name="event_type",
        ),
        CheckConstraint(
            "note IS NULL OR length(trim(note)) BETWEEN 1 AND 2000", name="note_length"
        ),
        Index(
            "ix_delivery_events_delivery_created_id", "delivery_id", "created_at", "id"
        ),
    )
    delivery_id: Mapped[UUID] = mapped_column(
        ForeignKey("deliveries.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)


# Read-only derived permission, returned only in owner report contracts. It is
# fetched with the report query, without adding a column or per-report queries.
ObjectReport.__mapper__.add_property(
    "evidence_locked",
    column_property(
        select(func.count())
        .select_from(OwnershipClaim)
        .join(
            ObjectMatch,
            ObjectMatch.id == OwnershipClaim.match_id,
        )
        .where(
            OwnershipClaim.status.in_(["pending", "approved"]),
            or_(
                ObjectMatch.lost_report_id == ObjectReport.id,
                ObjectMatch.found_report_id == ObjectReport.id,
            ),
        )
        .correlate_except(OwnershipClaim, ObjectMatch)
        .scalar_subquery()
        > 0
    ),
)
