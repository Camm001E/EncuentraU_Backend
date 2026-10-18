from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.object_matches import MatchStatus, ObjectMatch
from app.domain.ownership import (
    MAX_EVIDENCE_LENGTH,
    MAX_NOTE_LENGTH,
    MIN_EVIDENCE_LENGTH,
    AdminClaimView,
    ClaimContext,
    ClaimStatus,
    ClaimView,
    OwnershipClaim,
    WorkflowConflict,
    WorkflowForbidden,
    WorkflowNotFound,
    WorkflowPage,
    normalize_text,
    require_admin,
    validate_page,
    validate_text,
)
from app.domain.ports.ownership import OwnershipClaimRepository
from app.domain.users import User


def participant_view(context: ClaimContext, user: User) -> ClaimView:
    claim = context.claim
    if (
        claim is None
        or not user.is_active
        or user.id not in (claim.claimant_user_id, claim.custodian_user_id)
    ):
        raise WorkflowNotFound
    mine = user.id == claim.claimant_user_id
    match = context.match
    if not mine:
        match = replace(
            match, my_report=match.candidate_report, candidate_report=match.my_report
        )
    return ClaimView(
        claim.id,
        claim.match_id,
        claim.status,
        "claimant" if mine else "custodian",
        claim.ownership_evidence if mine else None,
        claim.rejection_reason,
        claim.reviewed_at,
        claim.created_at,
        claim.updated_at,
        context.conversation_id,
        match,
    )


def admin_view(context: ClaimContext) -> AdminClaimView:
    claim = context.claim
    if claim is None:
        raise WorkflowNotFound
    return AdminClaimView(
        claim.id,
        claim.match_id,
        claim.status,
        claim.ownership_evidence,
        context.lost_private_feature,
        context.found_private_feature,
        claim.admin_note,
        claim.rejection_reason,
        claim.reviewed_at,
        claim.created_at,
        claim.updated_at,
        context.conversation_id,
        context.match,
    )


class SubmitOwnershipClaim:
    def __init__(self, repository: OwnershipClaimRepository):
        self.repository = repository

    def __call__(self, match_id: UUID, user: User, evidence: str) -> ClaimView:
        evidence = validate_text(evidence, MIN_EVIDENCE_LENGTH, MAX_EVIDENCE_LENGTH)
        with self.repository.transaction(match_id=match_id) as context:
            if (
                context is None
                or not user.is_active
                or context.lost_owner_id != user.id
            ):
                raise WorkflowNotFound
            context.validate_pending_pair()
            if context.claim is not None:
                if (
                    context.claim.status != ClaimStatus.PENDING
                    or context.claim.ownership_evidence != evidence
                ):
                    raise WorkflowConflict
                return participant_view(context, user)
            now = datetime.now(UTC)
            claim = OwnershipClaim(
                uuid4(),
                match_id,
                user.id,
                context.found_owner_id,
                ClaimStatus.PENDING,
                evidence,
                None,
                None,
                None,
                None,
                now,
                now,
            )
            self.repository.add(claim)
            return participant_view(replace(context, claim=claim), user)


class GetClaim:
    def __init__(self, repository: OwnershipClaimRepository):
        self.repository = repository

    def __call__(
        self, user: User, *, claim_id: UUID | None = None, match_id: UUID | None = None
    ) -> ClaimView:
        context = self.repository.get_context(claim_id=claim_id, match_id=match_id)
        if context is None:
            raise WorkflowNotFound
        return participant_view(context, user)


class ListMyClaims:
    def __init__(self, repository: OwnershipClaimRepository):
        self.repository = repository

    def __call__(
        self,
        user: User,
        *,
        limit: int = 20,
        offset: int = 0,
        status: ClaimStatus | None = None,
    ) -> WorkflowPage[ClaimView]:
        validate_page(limit, offset)
        if not user.is_active:
            raise WorkflowNotFound
        page = self.repository.list_contexts(
            user_id=user.id, status=status, limit=limit, offset=offset
        )
        return replace(
            page, items=tuple(participant_view(item, user) for item in page.items)
        )


class ListAdminClaims:
    def __init__(self, repository: OwnershipClaimRepository):
        self.repository = repository

    def __call__(
        self,
        user: User,
        *,
        limit: int = 20,
        offset: int = 0,
        status: ClaimStatus | None = None,
    ) -> WorkflowPage[AdminClaimView]:
        require_admin(user)
        validate_page(limit, offset)
        page = self.repository.list_contexts(
            user_id=None, status=status, limit=limit, offset=offset
        )
        return replace(page, items=tuple(admin_view(item) for item in page.items))


class GetAdminClaim:
    def __init__(self, repository: OwnershipClaimRepository):
        self.repository = repository

    def __call__(self, claim_id: UUID, user: User) -> AdminClaimView:
        require_admin(user)
        context = self.repository.get_context(claim_id=claim_id)
        if context is None:
            raise WorkflowNotFound
        return admin_view(context)


class ReviewClaim:
    def __init__(self, repository: OwnershipClaimRepository):
        self.repository = repository

    def review(
        self,
        claim_id: UUID,
        user: User,
        *,
        approved: bool,
        admin_note: str | None,
        rejection_reason: str | None,
    ) -> AdminClaimView:
        require_admin(user)
        note = (
            validate_text(admin_note, 1, MAX_NOTE_LENGTH)
            if admin_note and normalize_text(admin_note)
            else None
        )
        reason = (
            None
            if approved
            else validate_text(rejection_reason or "", 3, MAX_NOTE_LENGTH)
        )
        with self.repository.transaction(claim_id=claim_id) as context:
            if context is None or context.claim is None:
                raise WorkflowNotFound
            claim = context.claim
            if user.id in (claim.claimant_user_id, claim.custodian_user_id):
                raise WorkflowForbidden
            context.validate_pending_pair()
            if claim.status != ClaimStatus.PENDING:
                raise WorkflowConflict
            if (claim.claimant_user_id, claim.custodian_user_id) != (
                context.lost_owner_id,
                context.found_owner_id,
            ):
                raise WorkflowConflict
            now = datetime.now(UTC)
            decided = replace(
                claim,
                status=ClaimStatus.APPROVED if approved else ClaimStatus.REJECTED,
                admin_id=user.id,
                admin_note=note,
                rejection_reason=reason,
                reviewed_at=now,
                updated_at=now,
            )
            conversation_id = self.repository.decide(context, decided)
            match: ObjectMatch = replace(
                context.match,
                status=MatchStatus.ACCEPTED if approved else MatchStatus.REJECTED,
                updated_at=now,
            )
            return admin_view(
                replace(
                    context, claim=decided, conversation_id=conversation_id, match=match
                )
            )


class ApproveClaim(ReviewClaim):
    def __call__(
        self, claim_id: UUID, user: User, admin_note: str | None = None
    ) -> AdminClaimView:
        return self.review(
            claim_id, user, approved=True, admin_note=admin_note, rejection_reason=None
        )


class RejectClaim(ReviewClaim):
    def __call__(
        self,
        claim_id: UUID,
        user: User,
        rejection_reason: str,
        admin_note: str | None = None,
    ) -> AdminClaimView:
        return self.review(
            claim_id,
            user,
            approved=False,
            admin_note=admin_note,
            rejection_reason=rejection_reason,
        )
