from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import get_current_user
from app.api.dependencies.ownership import (
    get_admin,
    get_claim_repository,
)
from app.api.dependencies.privacy import private_response
from app.api.schemas.ownership import (
    AdminClaimListResponse,
    AdminClaimResponse,
    ApprovalRequest,
    ClaimListResponse,
    ClaimRequest,
    ClaimResponse,
    RejectionRequest,
)
from app.application.ownership_claims import (
    ApproveClaim,
    GetAdminClaim,
    GetClaim,
    ListAdminClaims,
    ListMyClaims,
    RejectClaim,
    SubmitOwnershipClaim,
)
from app.domain.ownership import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, ClaimStatus
from app.domain.ports.ownership import OwnershipClaimRepository
from app.domain.users import User

router = APIRouter(
    tags=["ownership"], route_class=AuthRoute, dependencies=[Depends(private_response)]
)
CurrentUser = Annotated[User, Depends(get_current_user)]
Admin = Annotated[User, Depends(get_admin)]
Repository = Annotated[OwnershipClaimRepository, Depends(get_claim_repository)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
Offset = Annotated[int, Query(ge=0)]


@router.post(
    "/matches/{match_id}/claims",
    response_model=ClaimResponse,
    response_model_exclude_none=True,
    status_code=201,
)
def submit_claim(
    match_id: UUID, request: ClaimRequest, user: CurrentUser, repository: Repository
):
    return ClaimResponse.from_view(
        SubmitOwnershipClaim(repository)(match_id, user, request.ownership_evidence)
    )


@router.get(
    "/claims/me", response_model=ClaimListResponse, response_model_exclude_none=True
)
def list_my_claims(
    user: CurrentUser,
    repository: Repository,
    limit: Limit = DEFAULT_PAGE_LIMIT,
    offset: Offset = 0,
    status: ClaimStatus | None = None,
):
    return ClaimListResponse.from_page(
        ListMyClaims(repository)(user, limit=limit, offset=offset, status=status)
    )


@router.get(
    "/matches/{match_id}/claim",
    response_model=ClaimResponse,
    response_model_exclude_none=True,
)
def get_match_claim(match_id: UUID, user: CurrentUser, repository: Repository):
    return ClaimResponse.from_view(GetClaim(repository)(user, match_id=match_id))


@router.get(
    "/claims/{claim_id}", response_model=ClaimResponse, response_model_exclude_none=True
)
def get_claim(claim_id: UUID, user: CurrentUser, repository: Repository):
    return ClaimResponse.from_view(GetClaim(repository)(user, claim_id=claim_id))


@router.get("/admin/claims", response_model=AdminClaimListResponse)
def list_admin_claims(
    user: Admin,
    repository: Repository,
    limit: Limit = DEFAULT_PAGE_LIMIT,
    offset: Offset = 0,
    status: ClaimStatus | None = None,
):
    return AdminClaimListResponse.from_page(
        ListAdminClaims(repository)(user, limit=limit, offset=offset, status=status)
    )


@router.get("/admin/claims/{claim_id}", response_model=AdminClaimResponse)
def get_admin_claim(claim_id: UUID, user: Admin, repository: Repository):
    return AdminClaimResponse.from_view(GetAdminClaim(repository)(claim_id, user))


@router.post("/admin/claims/{claim_id}/approve", response_model=AdminClaimResponse)
def approve_claim(
    claim_id: UUID,
    user: Admin,
    repository: Repository,
    request: ApprovalRequest | None = None,
):
    return AdminClaimResponse.from_view(
        ApproveClaim(repository)(
            claim_id, user, request.admin_note if request else None
        )
    )


@router.post("/admin/claims/{claim_id}/reject", response_model=AdminClaimResponse)
def reject_claim(
    claim_id: UUID, request: RejectionRequest, user: Admin, repository: Repository
):
    return AdminClaimResponse.from_view(
        RejectClaim(repository)(
            claim_id, user, request.rejection_reason, request.admin_note
        )
    )
