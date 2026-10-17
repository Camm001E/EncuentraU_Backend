from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from app.domain.matching import MatchEvaluation
from app.domain.object_reports import ReportStatus, ReportType

MAX_MATCH_DAYS = 14
MIN_MATCH_PERCENTAGE = 60
DEFAULT_MATCH_LIMIT = 20
MAX_MATCH_LIMIT = 100


class MatchStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ObjectMatchError(Exception):
    message = "No se pudo completar la operación de coincidencias."


class MatchNotFoundError(ObjectMatchError):
    message = "Coincidencia no encontrada."


class MatchValidationError(ObjectMatchError):
    message = "Los filtros o la paginación no son válidos."


class MatchPersistenceError(ObjectMatchError):
    message = "El servicio de coincidencias no está disponible."


@dataclass(frozen=True, slots=True)
class ReportSummary:
    """Public allowlist: never carries ownership, private details or raw analysis."""

    id: UUID
    report_type: ReportType
    status: ReportStatus
    object_type: str
    category: str
    primary_color: str | None
    secondary_colors: tuple[str, ...]
    brand: str | None
    shape: str | None
    description: str
    location: str
    event_date: date


@dataclass(frozen=True, slots=True)
class MatchProposal:
    lost_report_id: UUID
    found_report_id: UUID
    evaluation: MatchEvaluation


@dataclass(frozen=True, slots=True)
class ObjectMatch:
    id: UUID
    evaluation: MatchEvaluation
    status: MatchStatus
    created_at: datetime
    updated_at: datetime
    my_report: ReportSummary
    candidate_report: ReportSummary


@dataclass(frozen=True, slots=True)
class MatchPage:
    items: tuple[ObjectMatch, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class GeneratedMatches:
    report_id: UUID
    items: tuple[ObjectMatch, ...]
