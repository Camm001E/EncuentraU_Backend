from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.object_matches import ObjectMatchResponse, ReportSummaryResponse
from app.domain.ownership import (
    MAX_EVIDENCE_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_NOTE_LENGTH,
    MIN_EVIDENCE_LENGTH,
    AdminClaimView,
    ClaimStatus,
    ClaimView,
    ConversationStatus,
    ConversationView,
    Message,
    MessagePage,
    WorkflowPage,
    normalize_text,
)


class PrivateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_fields(cls, value):
        return normalize_text(value) if isinstance(value, str) else value


class ClaimRequest(PrivateInput):
    ownership_evidence: Annotated[
        str, Field(min_length=MIN_EVIDENCE_LENGTH, max_length=MAX_EVIDENCE_LENGTH)
    ]


class ApprovalRequest(PrivateInput):
    admin_note: Annotated[str | None, Field(max_length=MAX_NOTE_LENGTH)] = None


class RejectionRequest(ApprovalRequest):
    rejection_reason: Annotated[str, Field(min_length=3, max_length=MAX_NOTE_LENGTH)]


class ClaimBaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    match_id: UUID
    status: ClaimStatus
    rejection_reason: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    conversation_id: UUID | None
    match: ObjectMatchResponse


class ClaimResponse(ClaimBaseResponse):
    relationship: Literal["claimant", "custodian"]
    ownership_evidence: str | None = None

    @classmethod
    def from_view(cls, view: ClaimView):
        return cls(
            **{**asdict(view), "match": ObjectMatchResponse.from_match(view.match)}
        )


class AdminClaimResponse(ClaimBaseResponse):
    ownership_evidence: str
    lost_private_feature: str | None
    found_private_feature: str | None
    admin_note: str | None

    @classmethod
    def from_view(cls, view: AdminClaimView):
        return cls(
            **{**asdict(view), "match": ObjectMatchResponse.from_match(view.match)}
        )


class ClaimListResponse(BaseModel):
    items: list[ClaimResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: WorkflowPage):
        return cls(
            items=[ClaimResponse.from_view(v) for v in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class AdminClaimListResponse(BaseModel):
    items: list[ClaimBaseResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: WorkflowPage):
        return cls(
            items=[
                ClaimBaseResponse(
                    **{
                        **{
                            key: getattr(v, key)
                            for key in ClaimBaseResponse.model_fields
                            if key != "match"
                        },
                        "match": ObjectMatchResponse.from_match(v.match),
                    }
                )
                for v in page.items
            ],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class MessageRequest(PrivateInput):
    body: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]
    client_message_id: UUID


class ReadRequest(PrivateInput):
    last_message_id: UUID | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    client_message_id: UUID
    body: str
    is_mine: bool
    created_at: datetime

    @classmethod
    def from_message(cls, message: Message):
        return cls(**asdict(message))


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None
    limit: int

    @classmethod
    def from_page(cls, page: MessagePage):
        return cls(
            items=[MessageResponse.from_message(v) for v in page.items],
            next_cursor=page.next_cursor,
            limit=page.limit,
        )


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    match_id: UUID
    claim_id: UUID
    status: ConversationStatus
    other_display_name: str
    report: ReportSummaryResponse
    last_message: MessageResponse | None
    last_message_at: datetime | None
    unread_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view: ConversationView):
        return cls(**asdict(view))


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: WorkflowPage):
        return cls(
            items=[ConversationResponse.from_view(v) for v in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
