from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from functools import wraps
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased, selectinload

from app.domain.object_matches import MatchStatus
from app.domain.ownership import (
    ClaimContext,
    ClaimStatus,
    OwnershipClaim,
    WorkflowPage,
    WorkflowUnavailable,
    aware,
)
from app.infrastructure.database.models import Conversation, ConversationParticipant
from app.infrastructure.database.models import ObjectMatch as MatchModel
from app.infrastructure.database.models import ObjectReport as ReportModel
from app.infrastructure.database.models import OwnershipClaim as ClaimModel
from app.infrastructure.database.object_match_repository import (
    GENERATION_LOCK_KEY,
    SQLAlchemyObjectMatchRepository,
)


def controlled(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except SQLAlchemyError:
            self.session.rollback()
            raise WorkflowUnavailable from None

    return wrapped


def claim_entity(model: ClaimModel) -> OwnershipClaim:
    values = {
        name: getattr(model, name) for name in OwnershipClaim.__dataclass_fields__
    }
    values["status"] = ClaimStatus(values["status"])
    for field in ("created_at", "updated_at", "reviewed_at"):
        if values[field] is not None:
            values[field] = aware(values[field])
    return OwnershipClaim(**values)


class SQLAlchemyOwnershipClaimRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def query():
        lost, found = (
            aliased(ReportModel, name="claim_lost"),
            aliased(ReportModel, name="claim_found"),
        )
        return (
            select(MatchModel, lost, found, ClaimModel, Conversation.id)
            .join(lost, MatchModel.lost_report_id == lost.id)
            .join(found, MatchModel.found_report_id == found.id)
            .outerjoin(ClaimModel, ClaimModel.match_id == MatchModel.id)
            .outerjoin(Conversation, Conversation.claim_id == ClaimModel.id)
            .options(selectinload(lost.image), selectinload(found.image))
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def context(row) -> ClaimContext:
        match, lost, found, claim, conversation_id = row
        return ClaimContext(
            SQLAlchemyObjectMatchRepository._to_domain(
                (match, lost, found), lost.user_id
            ),
            lost.user_id,
            found.user_id,
            lost.private_feature,
            found.private_feature,
            claim_entity(claim) if claim else None,
            conversation_id,
        )

    @controlled
    def get_context(
        self, *, match_id: UUID | None = None, claim_id: UUID | None = None
    ) -> ClaimContext | None:
        query = self.query()
        if claim_id is not None:
            query = query.where(ClaimModel.id == claim_id)
        elif match_id is not None:
            query = query.where(MatchModel.id == match_id)
        else:
            return None
        row = self.session.execute(query).first()
        return self.context(row) if row else None

    @contextmanager
    def transaction(
        self, *, match_id: UUID | None = None, claim_id: UUID | None = None
    ) -> Iterator[ClaimContext | None]:
        try:
            # Share the generator's gate: it must not delete or replace a pair
            # while a claim is submitted or a final decision is committed.
            if self.session.get_bind().dialect.name == "postgresql":
                self.session.execute(
                    select(func.pg_advisory_xact_lock(GENERATION_LOCK_KEY))
                )
            if claim_id is not None:
                match_id = self.session.scalar(
                    select(ClaimModel.match_id).where(ClaimModel.id == claim_id)
                )
            match = self.session.scalar(
                select(MatchModel)
                .where(MatchModel.id == match_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if match is not None:
                self.session.scalars(
                    select(ReportModel)
                    .where(
                        ReportModel.id.in_(
                            [match.lost_report_id, match.found_report_id]
                        )
                    )
                    .order_by(ReportModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                ).all()
                self.session.scalar(
                    select(ClaimModel)
                    .where(ClaimModel.match_id == match_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            yield self.get_context(match_id=match_id) if match is not None else None
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise WorkflowUnavailable from None
        except Exception:
            self.session.rollback()
            raise

    @controlled
    def add(self, claim: OwnershipClaim) -> None:
        self.session.add(ClaimModel(**asdict(claim)))
        self.session.flush()

    @controlled
    def list_contexts(
        self,
        *,
        user_id: UUID | None,
        status: ClaimStatus | None,
        limit: int,
        offset: int,
    ) -> WorkflowPage[ClaimContext]:
        query = self.query().where(ClaimModel.id.is_not(None))
        if user_id is not None:
            query = query.where(
                or_(
                    ClaimModel.claimant_user_id == user_id,
                    ClaimModel.custodian_user_id == user_id,
                )
            )
        if status is not None:
            query = query.where(ClaimModel.status == status)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        ordering = (
            (ClaimModel.created_at, ClaimModel.id)
            if user_id is None
            else (ClaimModel.created_at.desc(), ClaimModel.id.desc())
        )
        rows = self.session.execute(
            query.order_by(*ordering).limit(limit).offset(offset)
        ).all()
        return WorkflowPage(
            tuple(self.context(row) for row in rows), total, limit, offset
        )

    @controlled
    def decide(self, context: ClaimContext, claim: OwnershipClaim) -> UUID | None:
        record = self.session.get(ClaimModel, claim.id)
        for name in (
            "status",
            "admin_id",
            "admin_note",
            "rejection_reason",
            "reviewed_at",
            "updated_at",
        ):
            setattr(record, name, getattr(claim, name))
        match = self.session.get(MatchModel, claim.match_id)
        approved = claim.status == ClaimStatus.APPROVED
        match.status = MatchStatus.ACCEPTED if approved else MatchStatus.REJECTED
        match.updated_at = claim.updated_at
        self.session.flush()
        if not approved:
            return None
        identifier = uuid4()
        self.session.add(
            Conversation(
                id=identifier,
                match_id=claim.match_id,
                claim_id=claim.id,
                status="active",
                created_at=claim.updated_at,
                updated_at=claim.updated_at,
            )
        )
        self.session.flush()
        self.session.add_all(
            [
                ConversationParticipant(
                    conversation_id=identifier,
                    user_id=user_id,
                    joined_at=claim.updated_at,
                )
                for user_id in (claim.claimant_user_id, claim.custodian_user_id)
            ]
        )
        self.session.flush()
        return identifier
