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
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class ObjectMatch(UUIDPrimaryKey, CreatedAt, Base):
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
