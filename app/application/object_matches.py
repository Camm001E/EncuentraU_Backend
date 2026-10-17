from uuid import UUID

from app.application.matching_service import MatchingService
from app.domain.matching import MatchableObject, MatchLevel, MatchRequest
from app.domain.object_matches import (
    DEFAULT_MATCH_LIMIT,
    MAX_MATCH_DAYS,
    MAX_MATCH_LIMIT,
    MIN_MATCH_PERCENTAGE,
    GeneratedMatches,
    MatchNotFoundError,
    MatchPage,
    MatchProposal,
    MatchStatus,
    MatchValidationError,
    ObjectMatch,
)
from app.domain.object_reports import (
    ObjectReport,
    ReportNotActiveError,
    ReportStatus,
    ReportType,
)
from app.domain.ports.object_match_repository import ObjectMatchRepository


def to_matchable_object(report: ObjectReport) -> MatchableObject:
    """User attributes win; only known visual fields supplement them."""
    attributes = report.attributes
    data = report.analysis.data.extracted_data if report.analysis else {}

    def image_text(name: str, maximum: int) -> str | None:
        value = data.get(name)
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value if value and len(value) <= maximum else None

    def image_list(name: str, maximum: int, item_limit: int) -> list[str]:
        values = data.get(name)
        if not isinstance(values, list):
            return []
        return list(
            dict.fromkeys(
                item.strip()
                for item in values
                if isinstance(item, str)
                and item.strip()
                and len(item.strip()) <= item_limit
            )
        )[:maximum]

    return MatchableObject(
        object_type=attributes.object_type,
        category=attributes.category,
        primary_color=attributes.primary_color or image_text("primary_color", 100),
        secondary_colors=list(attributes.secondary_colors)
        or image_list("secondary_colors", 20, 100),
        brand=attributes.brand or image_text("brand", 100),
        shape=attributes.shape or image_text("shape", 500),
        visible_features=image_list("visible_features", 50, 2000),
        visible_text=image_list("visible_text", 50, 2000),
        description=attributes.description,
        location=attributes.location,
        event_date=attributes.event_date,
    )


class GenerateReportMatches:
    def __init__(self, repository: ObjectMatchRepository, matching: MatchingService):
        self.repository = repository
        self.matching = matching

    def __call__(self, report_id: UUID, user_id: UUID) -> GeneratedMatches:
        with self.repository.generation(report_id, user_id) as batch:
            source = batch.source
            if source.status != ReportStatus.ACTIVE:
                raise ReportNotActiveError
            proposals = []
            for candidate in batch.candidates:
                if (
                    candidate.user_id == source.user_id
                    or candidate.report_type == source.report_type
                    or candidate.status != ReportStatus.ACTIVE
                ):
                    continue
                lost, found = (
                    (source, candidate)
                    if source.report_type == ReportType.LOST
                    else (candidate, source)
                )
                days = (found.attributes.event_date - lost.attributes.event_date).days
                if not 0 <= days <= MAX_MATCH_DAYS:
                    continue
                evaluation = self.matching.evaluate(
                    MatchRequest(
                        lost=to_matchable_object(lost),
                        found=to_matchable_object(found),
                    )
                )
                if (
                    evaluation.compatible
                    and evaluation.percentage >= MIN_MATCH_PERCENTAGE
                    and evaluation.level in {MatchLevel.HIGH, MatchLevel.POSSIBLE}
                ):
                    proposals.append(MatchProposal(lost.id, found.id, evaluation))
            items = self.repository.synchronize(source, tuple(proposals))
        return GeneratedMatches(report_id, items)


class ListMyMatches:
    def __init__(self, repository: ObjectMatchRepository):
        self.repository = repository

    def __call__(
        self,
        user_id: UUID,
        *,
        limit: int = DEFAULT_MATCH_LIMIT,
        offset: int = 0,
        level: MatchLevel | None = None,
        status: MatchStatus | None = None,
    ) -> MatchPage:
        if not 1 <= limit <= MAX_MATCH_LIMIT or offset < 0:
            raise MatchValidationError
        return self.repository.list_by_user(
            user_id, limit=limit, offset=offset, level=level, status=status
        )


class GetMyMatch:
    def __init__(self, repository: ObjectMatchRepository):
        self.repository = repository

    def __call__(self, match_id: UUID, user_id: UUID) -> ObjectMatch:
        match = self.repository.get_by_id_and_user(match_id, user_id)
        if match is None:
            raise MatchNotFoundError
        return match
