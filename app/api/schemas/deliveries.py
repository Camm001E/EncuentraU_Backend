from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.object_matches import ReportSummaryResponse
from app.api.schemas.ownership import AdminClaimResponse, PrivateInput
from app.application.ownership_claims import admin_view
from app.domain.deliveries import DeliveryContext, DeliveryEventType, DeliveryStatus


class DisputeRequest(PrivateInput):
    reason: Annotated[str, Field(min_length=10, max_length=2000, repr=False)]


class DeliveryNoteRequest(PrivateInput):
    admin_note: Annotated[
        str | None, Field(min_length=1, max_length=2000, repr=False)
    ] = None


class ReopenRequest(PrivateInput):
    admin_note: Annotated[str, Field(min_length=1, max_length=2000, repr=False)]


class DeliveryEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    event_type: DeliveryEventType
    actor: Literal["claimant", "custodian", "admin"]
    note: str | None = Field(repr=False)
    created_at: datetime


def event_views(context: DeliveryContext, *, admin: bool = False):
    claim = context.claim_context.claim
    return [
        DeliveryEventResponse(
            id=e.id,
            event_type=e.event_type,
            actor=(
                "claimant"
                if e.actor_user_id == claim.claimant_user_id
                else "custodian"
                if e.actor_user_id == claim.custodian_user_id
                else "admin"
            ),
            note=e.note
            if admin or e.event_type == DeliveryEventType.DISPUTE_OPENED
            else None,
            created_at=e.created_at,
        )
        for e in context.events
    ]


class DeliverySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    match_id: UUID
    claim_id: UUID
    conversation_id: UUID
    status: DeliveryStatus
    claimant_confirmed_at: datetime | None
    custodian_confirmed_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    conversation_status: str
    lost_report: ReportSummaryResponse
    found_report: ReportSummaryResponse

    @classmethod
    def values(cls, context):
        from dataclasses import asdict

        d = context.delivery
        return {
            **{
                key: getattr(d, key)
                for key in (
                    "id",
                    "match_id",
                    "claim_id",
                    "conversation_id",
                    "status",
                    "claimant_confirmed_at",
                    "custodian_confirmed_at",
                    "completed_at",
                    "created_at",
                    "updated_at",
                )
            },
            "conversation_status": context.conversation_status,
            "lost_report": ReportSummaryResponse(
                **asdict(context.claim_context.match.my_report)
            ),
            "found_report": ReportSummaryResponse(
                **asdict(context.claim_context.match.candidate_report)
            ),
        }


class DeliveryResponse(DeliverySummaryResponse):
    relationship: Literal["claimant", "custodian"]
    my_confirmed_at: datetime | None
    other_confirmed_at: datetime | None
    can_confirm: bool
    can_dispute: bool
    dispute_reason: str | None = Field(repr=False)
    events: list[DeliveryEventResponse]

    @classmethod
    def from_context(cls, context, user):
        role = context.relationship(user)
        d = context.delivery
        mine = getattr(d, f"{role}_confirmed_at")
        other = (
            d.custodian_confirmed_at if role == "claimant" else d.claimant_confirmed_at
        )
        return cls(
            **cls.values(context),
            relationship=role,
            my_confirmed_at=mine,
            other_confirmed_at=other,
            can_confirm=mine is None
            and d.status
            in (DeliveryStatus.COORDINATING, DeliveryStatus.AWAITING_CONFIRMATIONS),
            can_dispute=d.status
            not in (DeliveryStatus.DISPUTED, DeliveryStatus.COMPLETED),
            dispute_reason=d.dispute_reason,
            events=event_views(context),
        )


class AdminDeliveryResponse(DeliverySummaryResponse):
    claim: AdminClaimResponse = Field(repr=False)
    dispute_reason: str | None = Field(repr=False)
    admin_note: str | None = Field(repr=False)
    events: list[DeliveryEventResponse]
    message_count: int
    last_activity_at: datetime | None

    @classmethod
    def from_context(cls, context):
        return cls(
            **cls.values(context),
            claim=AdminClaimResponse.from_view(admin_view(context.claim_context)),
            dispute_reason=context.delivery.dispute_reason,
            admin_note=context.delivery.admin_note,
            events=event_views(context, admin=True),
            message_count=context.message_count,
            last_activity_at=context.last_activity_at,
        )


class DeliveryListResponse(BaseModel):
    items: list[DeliveryResponse]
    total: int
    limit: int
    offset: int


class AdminDeliveryListResponse(BaseModel):
    items: list[DeliverySummaryResponse]
    total: int
    limit: int
    offset: int
