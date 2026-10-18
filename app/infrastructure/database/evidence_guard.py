"""A common lock order serializes evidence writes with claims and generation."""

from sqlalchemy import func, or_, select

from app.domain.ownership import EVIDENCE_PROTECTED_MESSAGE, WorkflowConflict
from app.infrastructure.database.models import ObjectMatch, OwnershipClaim
from app.infrastructure.database.workflow_lock import GENERATION_LOCK_KEY


def workflow_gate(session):
    if session.get_bind().dialect.name == "postgresql":
        session.execute(select(func.pg_advisory_xact_lock(GENERATION_LOCK_KEY)))


def require_mutable_evidence(session, report_id):
    claimed = session.scalar(
        select(OwnershipClaim.id)
        .join(
            ObjectMatch,
            ObjectMatch.id == OwnershipClaim.match_id,
        )
        .where(
            OwnershipClaim.status.in_(["pending", "approved"]),
            or_(
                ObjectMatch.lost_report_id == report_id,
                ObjectMatch.found_report_id == report_id,
            ),
        )
        .limit(1)
    )
    if claimed is not None:
        error = WorkflowConflict()
        error.message = EVIDENCE_PROTECTED_MESSAGE
        raise error
