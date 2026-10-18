"""Delivery state machine and private views, independent of transport/storage."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.ownership import (
    ClaimContext,
    ConversationStatus,
    WorkflowConflict,
    WorkflowNotFound,
)
from app.domain.users import User

MIN_DISPUTE_LENGTH = 10
MAX_DELIVERY_NOTE_LENGTH = 2000


class DeliveryStatus(StrEnum):
    COORDINATING = "coordinating"
    AWAITING_CONFIRMATIONS = "awaiting_confirmations"
    AWAITING_ADMIN = "awaiting_admin"
    DISPUTED = "disputed"
    COMPLETED = "completed"


class DeliveryEventType(StrEnum):
    DELIVERY_CREATED = "delivery_created"
    CUSTODIAN_CONFIRMED = "custodian_confirmed"
    CLAIMANT_CONFIRMED = "claimant_confirmed"
    DISPUTE_OPENED = "dispute_opened"
    ADMIN_REOPENED = "admin_reopened"
    ADMIN_COMPLETED = "admin_completed"


@dataclass(frozen=True, slots=True)
class Delivery:
    id: UUID
    match_id: UUID
    claim_id: UUID
    conversation_id: UUID
    status: DeliveryStatus
    claimant_confirmed_at: datetime | None
    custodian_confirmed_at: datetime | None
    dispute_raised_by_user_id: UUID | None = field(repr=False)
    dispute_reason: str | None = field(repr=False)
    admin_id: UUID | None = field(repr=False)
    admin_note: str | None = field(repr=False)
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def confirm(self, relationship: str, now: datetime) -> "Delivery":
        if self.status not in (
            DeliveryStatus.COORDINATING,
            DeliveryStatus.AWAITING_CONFIRMATIONS,
            DeliveryStatus.AWAITING_ADMIN,
        ):
            raise WorkflowConflict
        name = f"{relationship}_confirmed_at"
        if getattr(self, name) is not None:
            return self
        result = replace(self, **{name: now}, updated_at=now)
        return replace(
            result,
            status=(
                DeliveryStatus.AWAITING_ADMIN
                if result.claimant_confirmed_at and result.custodian_confirmed_at
                else DeliveryStatus.AWAITING_CONFIRMATIONS
            ),
        )

    def dispute(self, user_id: UUID, reason: str, now: datetime) -> "Delivery":
        if self.status in (DeliveryStatus.DISPUTED, DeliveryStatus.COMPLETED):
            raise WorkflowConflict
        return replace(
            self,
            status=DeliveryStatus.DISPUTED,
            dispute_raised_by_user_id=user_id,
            dispute_reason=reason,
            updated_at=now,
        )

    def reopen(self, admin: User, note: str, now: datetime) -> "Delivery":
        # Explicit administrative exception to the participant state machine.
        if self.status not in (DeliveryStatus.DISPUTED, DeliveryStatus.AWAITING_ADMIN):
            raise WorkflowConflict
        return replace(
            self,
            status=DeliveryStatus.COORDINATING,
            claimant_confirmed_at=None,
            custodian_confirmed_at=None,
            dispute_raised_by_user_id=None,
            dispute_reason=None,
            admin_id=admin.id,
            admin_note=note,
            updated_at=now,
        )

    def complete(self, admin: User, note: str | None, now: datetime) -> "Delivery":
        if (
            self.status != DeliveryStatus.AWAITING_ADMIN
            or not self.claimant_confirmed_at
            or not self.custodian_confirmed_at
        ):
            raise WorkflowConflict
        return replace(
            self,
            status=DeliveryStatus.COMPLETED,
            admin_id=admin.id,
            admin_note=note,
            completed_at=now,
            updated_at=now,
        )


@dataclass(frozen=True, slots=True)
class DeliveryEvent:
    id: UUID
    delivery_id: UUID
    actor_user_id: UUID = field(repr=False)
    event_type: DeliveryEventType
    note: str | None = field(repr=False)
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryContext:
    delivery: Delivery
    claim_context: ClaimContext = field(repr=False)
    conversation_status: ConversationStatus
    events: tuple[DeliveryEvent, ...]
    message_count: int
    last_activity_at: datetime | None

    def relationship(self, user: User) -> str:
        claim = self.claim_context.claim
        if not user.is_active or claim is None:
            raise WorkflowNotFound
        if user.id == claim.claimant_user_id:
            return "claimant"
        if user.id == claim.custodian_user_id:
            return "custodian"
        raise WorkflowNotFound

    def validate_active_case(self) -> None:
        context = self.claim_context
        if (
            context.claim is None
            or context.claim.status.value != "approved"
            or context.match.status.value != "accepted"
            or context.match.my_report.status.value != "active"
            or context.match.candidate_report.status.value != "active"
            or self.conversation_status != ConversationStatus.ACTIVE
        ):
            raise WorkflowConflict
