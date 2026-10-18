from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased, selectinload

from app.domain.matching import MatchEvaluation, MatchLevel
from app.domain.object_matches import (
    MAX_MATCH_DAYS,
    MatchPage,
    MatchPersistenceError,
    MatchProposal,
    MatchStatus,
    ObjectMatch,
    ReportSummary,
)
from app.domain.object_reports import (
    ObjectReport,
    ReportNotFoundError,
    ReportStatus,
    ReportType,
)
from app.domain.ports.object_match_repository import MatchCandidates
from app.infrastructure.database.models import ObjectMatch as MatchModel
from app.infrastructure.database.models import ObjectReport as ReportModel
from app.infrastructure.database.models import OwnershipClaim as ClaimModel
from app.infrastructure.database.object_report_repository import (
    SQLAlchemyObjectReportRepository,
)
from app.infrastructure.database.report_image_repository import image_reference

# Generations can start at either end of a pair. A transaction-level gate gives
# upsert and stale-pair cleanup a consistent order across concurrent requests.
# This deliberately favors correctness over parallel generation throughput.
from app.infrastructure.database.workflow_lock import GENERATION_LOCK_KEY

METRIC_FIELDS = (
    "percentage",
    "identity_percentage",
    "context_percentage",
    "evidence_coverage",
    "compatible",
    "level",
    "factors",
    "warnings",
)


class SQLAlchemyObjectMatchRepository:
    def __init__(self, session: Session):
        self.session = session

    @contextmanager
    def generation(self, report_id: UUID, user_id: UUID) -> Iterator[MatchCandidates]:
        try:
            self.session.execute(
                select(func.pg_advisory_xact_lock(GENERATION_LOCK_KEY))
            )
            source = self.session.scalar(
                select(ReportModel)
                .where(ReportModel.id == report_id, ReportModel.user_id == user_id)
                .options(
                    selectinload(ReportModel.analyses), selectinload(ReportModel.image)
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if source is None:
                raise ReportNotFoundError
            is_lost = source.report_type == ReportType.LOST
            earliest = (
                source.event_date
                if is_lost
                else date.fromordinal(
                    max(
                        date.min.toordinal(),
                        source.event_date.toordinal() - MAX_MATCH_DAYS,
                    )
                )
            )
            latest = (
                date.fromordinal(
                    min(
                        date.max.toordinal(),
                        source.event_date.toordinal() + MAX_MATCH_DAYS,
                    )
                )
                if is_lost
                else source.event_date
            )
            candidates = self.session.scalars(
                select(ReportModel)
                .where(
                    ReportModel.user_id != user_id,
                    ReportModel.report_type
                    == (ReportType.FOUND if is_lost else ReportType.LOST),
                    ReportModel.status == ReportStatus.ACTIVE,
                    ReportModel.event_date.between(earliest, latest),
                )
                .order_by(ReportModel.id)
                .options(
                    selectinload(ReportModel.analyses), selectinload(ReportModel.image)
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            ).all()
            yield MatchCandidates(
                SQLAlchemyObjectReportRepository.to_domain(source),
                tuple(
                    SQLAlchemyObjectReportRepository.to_domain(item)
                    for item in candidates
                ),
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise MatchPersistenceError from None
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _involves(report_id: UUID):
        return or_(
            MatchModel.lost_report_id == report_id,
            MatchModel.found_report_id == report_id,
        )

    def synchronize(
        self,
        source: ObjectReport,
        proposals: tuple[MatchProposal, ...],
    ) -> tuple[ObjectMatch, ...]:
        is_lost = source.report_type == ReportType.LOST
        other_column = (
            MatchModel.found_report_id if is_lost else MatchModel.lost_report_id
        )
        retained = [
            p.found_report_id if is_lost else p.lost_report_id for p in proposals
        ]
        self.session.execute(
            delete(MatchModel).where(
                self._involves(source.id),
                MatchModel.status == MatchStatus.PENDING,
                ~select(ClaimModel.id)
                .where(ClaimModel.match_id == MatchModel.id)
                .exists(),
                other_column.not_in(retained),
            ),
            execution_options={"synchronize_session": False},
        )
        for proposal in sorted(
            proposals, key=lambda p: (p.lost_report_id, p.found_report_id)
        ):
            metrics = proposal.evaluation.model_dump(mode="json")
            statement = insert(MatchModel).values(
                id=uuid4(),
                lost_report_id=proposal.lost_report_id,
                found_report_id=proposal.found_report_id,
                status=MatchStatus.PENDING,
                **metrics,
            )
            self.session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_object_matches_pair",
                    set_={
                        **{
                            name: getattr(statement.excluded, name)
                            for name in METRIC_FIELDS
                        },
                        "updated_at": func.clock_timestamp(),
                    },
                    where=(MatchModel.status == MatchStatus.PENDING)
                    & ~select(ClaimModel.id)
                    .where(ClaimModel.match_id == MatchModel.id)
                    .exists(),
                )
            )
        statement = self._visible_query(source.user_id).where(self._involves(source.id))
        return tuple(
            self._to_domain(row, source.user_id)
            for row in self.session.execute(statement)
        )

    @staticmethod
    def _visible_query(user_id: UUID):
        lost = aliased(ReportModel, name="lost_report")
        found = aliased(ReportModel, name="found_report")
        return (
            select(MatchModel, lost, found)
            .join(lost, MatchModel.lost_report_id == lost.id)
            .join(found, MatchModel.found_report_id == found.id)
            .where(or_(lost.user_id == user_id, found.user_id == user_id))
            .options(selectinload(lost.image), selectinload(found.image))
            .order_by(
                MatchModel.percentage.desc(),
                MatchModel.created_at.desc(),
                MatchModel.id.desc(),
            )
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _summary(report: ReportModel) -> ReportSummary:
        return ReportSummary(
            id=report.id,
            report_type=ReportType(report.report_type),
            status=ReportStatus(report.status),
            object_type=report.object_type,
            category=report.category,
            primary_color=report.primary_color,
            secondary_colors=tuple(report.secondary_colors),
            brand=report.brand,
            shape=report.shape,
            description=report.description,
            location=report.location,
            event_date=report.event_date,
            image=image_reference(report.image) if report.image is not None else None,
        )

    @classmethod
    def _to_domain(cls, row, user_id: UUID) -> ObjectMatch:
        match, lost, found = row
        mine, candidate = (lost, found) if lost.user_id == user_id else (found, lost)
        return ObjectMatch(
            id=match.id,
            evaluation=MatchEvaluation(
                **{name: getattr(match, name) for name in METRIC_FIELDS}
            ),
            status=MatchStatus(match.status),
            created_at=match.created_at,
            updated_at=match.updated_at,
            my_report=cls._summary(mine),
            candidate_report=cls._summary(candidate),
        )

    def list_by_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        level: MatchLevel | None = None,
        status: MatchStatus | None = None,
    ) -> MatchPage:
        try:
            statement = self._visible_query(user_id)
            if level is not None:
                statement = statement.where(MatchModel.level == level)
            if status is not None:
                statement = statement.where(MatchModel.status == status)
            total = self.session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            rows = self.session.execute(statement.limit(limit).offset(offset))
            return MatchPage(
                tuple(self._to_domain(row, user_id) for row in rows),
                total,
                limit,
                offset,
            )
        except SQLAlchemyError:
            self.session.rollback()
            raise MatchPersistenceError from None

    def get_by_id_and_user(self, match_id: UUID, user_id: UUID) -> ObjectMatch | None:
        try:
            row = self.session.execute(
                self._visible_query(user_id).where(MatchModel.id == match_id)
            ).first()
            return self._to_domain(row, user_id) if row is not None else None
        except SQLAlchemyError:
            self.session.rollback()
            raise MatchPersistenceError from None
