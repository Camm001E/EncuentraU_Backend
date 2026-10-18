"""Ownership workflow and chat rules. No web, database or provider dependencies."""

import base64
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from app.domain.object_matches import MatchStatus, ObjectMatch, ReportSummary
from app.domain.object_reports import ReportStatus
from app.domain.users import User, UserRole

MIN_EVIDENCE_LENGTH = 10
MAX_EVIDENCE_LENGTH = 4000
MAX_NOTE_LENGTH = 2000
MAX_MESSAGE_LENGTH = 2000
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
EVIDENCE_PROTECTED_MESSAGE = (
    "El reporte y su fotografía están protegidos mientras se revisa "
    "o coordina una reclamación."
)


class ClaimStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class WorkflowError(Exception):
    message = "No se pudo completar la operación."


class WorkflowNotFound(WorkflowError):
    message = "Recurso no encontrado."


class WorkflowForbidden(WorkflowError):
    message = "Esta acción requiere una cuenta administradora activa."


class WorkflowConflict(WorkflowError):
    message = "El estado actual ya no permite esta operación. Actualiza la información."


class WorkflowValidation(WorkflowError):
    message = "Revisa la información y los límites permitidos."


class WorkflowUnavailable(WorkflowError):
    message = "El servicio no está disponible temporalmente. Inténtalo de nuevo."


def normalize_text(value: str) -> str:
    """Keep plain text and paragraphs; remove invisible control characters."""
    value = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    )
    value = "".join(
        c for c in value if c == "\n" or not unicodedata.category(c).startswith("C")
    )
    return "\n".join(line.strip() for line in value.split("\n")).strip()


def validate_text(value: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise WorkflowValidation
    value = normalize_text(value)
    if not minimum <= len(value) <= maximum:
        raise WorkflowValidation
    return value


def validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_PAGE_LIMIT or offset < 0:
        raise WorkflowValidation


def require_admin(user: User) -> User:
    if not user.is_active or user.role != UserRole.ADMIN:
        raise WorkflowForbidden
    return user


def display_name(full_name: str) -> str:
    first = full_name.strip().split()[0] if full_name.strip() else ""
    if not first or "@" in first or any(c.isdigit() for c in first):
        return "Estudiante"
    return first[:40]


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class OwnershipClaim:
    id: UUID
    match_id: UUID
    claimant_user_id: UUID = field(repr=False)
    custodian_user_id: UUID = field(repr=False)
    status: ClaimStatus
    ownership_evidence: str = field(repr=False)
    admin_id: UUID | None = field(repr=False)
    admin_note: str | None = field(repr=False)
    rejection_reason: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimContext:
    match: ObjectMatch
    lost_owner_id: UUID = field(repr=False)
    found_owner_id: UUID = field(repr=False)
    lost_private_feature: str | None = field(repr=False)
    found_private_feature: str | None = field(repr=False)
    claim: OwnershipClaim | None = None
    conversation_id: UUID | None = None

    def validate_pending_pair(self) -> None:
        if (
            self.lost_owner_id == self.found_owner_id
            or self.match.status != MatchStatus.PENDING
            or self.match.my_report.status != ReportStatus.ACTIVE
            or self.match.candidate_report.status != ReportStatus.ACTIVE
            or self.match.my_report.report_type.value != "lost"
            or self.match.candidate_report.report_type.value != "found"
        ):
            raise WorkflowConflict


@dataclass(frozen=True, slots=True)
class ClaimView:
    id: UUID
    match_id: UUID
    status: ClaimStatus
    relationship: str
    ownership_evidence: str | None
    rejection_reason: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    conversation_id: UUID | None
    match: ObjectMatch


@dataclass(frozen=True, slots=True)
class AdminClaimView:
    id: UUID
    match_id: UUID
    status: ClaimStatus
    ownership_evidence: str = field(repr=False)
    lost_private_feature: str | None = field(repr=False)
    found_private_feature: str | None = field(repr=False)
    admin_note: str | None = field(repr=False)
    rejection_reason: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    conversation_id: UUID | None
    match: ObjectMatch


@dataclass(frozen=True, slots=True)
class WorkflowPage[T]:
    items: tuple[T, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class ConversationAccess:
    id: UUID
    match_id: UUID
    claim_id: UUID
    status: ConversationStatus
    participants: tuple[UUID, ...] = field(repr=False)
    approved: bool

    def authorize(self, user: User, *, write: bool = False) -> None:
        if not user.is_active or user.id not in self.participants or not self.approved:
            raise WorkflowNotFound
        if write and self.status != ConversationStatus.ACTIVE:
            raise WorkflowConflict


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    client_message_id: UUID
    body: str = field(repr=False)
    is_mine: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationView:
    id: UUID
    match_id: UUID
    claim_id: UUID
    status: ConversationStatus
    other_display_name: str
    report: ReportSummary
    last_message: Message | None
    last_message_at: datetime | None
    unread_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageCursor:
    created_at: datetime
    id: UUID

    def encode(self) -> str:
        data = json.dumps([aware(self.created_at).isoformat(), str(self.id)]).encode()
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str | None) -> "MessageCursor | None":
        if value is None:
            return None
        try:
            if len(value) > 256:
                raise ValueError
            timestamp, identifier = json.loads(
                base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            )
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None:
                raise ValueError
            return cls(aware(parsed), UUID(identifier))
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
            raise WorkflowValidation from None


@dataclass(frozen=True, slots=True)
class MessagePage:
    items: tuple[Message, ...]
    next_cursor: str | None
    limit: int
