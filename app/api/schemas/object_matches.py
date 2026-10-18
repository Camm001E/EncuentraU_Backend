from dataclasses import asdict
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.schemas.report_images import ReportImageResponse
from app.domain.matching import MatchFactor, MatchLevel
from app.domain.object_matches import (
    GeneratedMatches,
    MatchPage,
    MatchStatus,
    ObjectMatch,
)
from app.domain.object_reports import ReportStatus, ReportType


class ReportSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    report_type: ReportType
    status: ReportStatus
    object_type: str
    category: str
    primary_color: str | None
    secondary_colors: list[str]
    brand: str | None
    shape: str | None
    description: str
    location: str
    event_date: date
    image: ReportImageResponse | None = None


class ObjectMatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    percentage: int
    identity_percentage: float
    context_percentage: float
    evidence_coverage: float
    compatible: bool
    level: MatchLevel
    status: MatchStatus
    factors: list[MatchFactor]
    warnings: list[str]
    created_at: datetime
    updated_at: datetime
    my_report: ReportSummaryResponse
    candidate_report: ReportSummaryResponse

    @classmethod
    def from_match(cls, match: ObjectMatch) -> "ObjectMatchResponse":
        return cls(
            id=match.id,
            **match.evaluation.model_dump(),
            status=match.status,
            created_at=match.created_at,
            updated_at=match.updated_at,
            my_report=ReportSummaryResponse(**asdict(match.my_report)),
            candidate_report=ReportSummaryResponse(**asdict(match.candidate_report)),
        )


class MatchListResponse(BaseModel):
    items: list[ObjectMatchResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: MatchPage) -> "MatchListResponse":
        return cls(
            items=[ObjectMatchResponse.from_match(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class GenerateMatchesResponse(BaseModel):
    report_id: UUID
    total: int
    items: list[ObjectMatchResponse]

    @classmethod
    def from_result(cls, result: GeneratedMatches) -> "GenerateMatchesResponse":
        return cls(
            report_id=result.report_id,
            total=len(result.items),
            items=[ObjectMatchResponse.from_match(item) for item in result.items],
        )
