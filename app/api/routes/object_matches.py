from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import get_current_user
from app.api.dependencies.object_matches import (
    get_match_repository,
    get_matching_service,
)
from app.api.schemas.object_matches import (
    GenerateMatchesResponse,
    MatchListResponse,
    ObjectMatchResponse,
)
from app.application.matching_service import MatchingService
from app.application.object_matches import (
    GenerateReportMatches,
    GetMyMatch,
    ListMyMatches,
)
from app.domain.matching import MatchLevel
from app.domain.object_matches import DEFAULT_MATCH_LIMIT, MAX_MATCH_LIMIT, MatchStatus
from app.domain.ports.object_match_repository import ObjectMatchRepository
from app.domain.users import User

router = APIRouter(tags=["matching"], route_class=AuthRoute)
CurrentUser = Annotated[User, Depends(get_current_user)]
Repository = Annotated[ObjectMatchRepository, Depends(get_match_repository)]


@router.post(
    "/reports/{report_id}/matches/generate", response_model=GenerateMatchesResponse
)
def generate_report_matches(
    report_id: UUID,
    user: CurrentUser,
    repository: Repository,
    matching: Annotated[MatchingService, Depends(get_matching_service)],
) -> GenerateMatchesResponse:
    return GenerateMatchesResponse.from_result(
        GenerateReportMatches(repository, matching)(report_id, user.id)
    )


@router.get("/matches/me", response_model=MatchListResponse)
def list_my_matches(
    user: CurrentUser,
    repository: Repository,
    limit: Annotated[int, Query(ge=1, le=MAX_MATCH_LIMIT)] = DEFAULT_MATCH_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    level: MatchLevel | None = None,
    status: MatchStatus | None = None,
) -> MatchListResponse:
    return MatchListResponse.from_page(
        ListMyMatches(repository)(
            user.id, limit=limit, offset=offset, level=level, status=status
        )
    )


@router.get("/matches/{match_id}", response_model=ObjectMatchResponse)
def get_my_match(
    match_id: UUID, user: CurrentUser, repository: Repository
) -> ObjectMatchResponse:
    return ObjectMatchResponse.from_match(GetMyMatch(repository)(match_id, user.id))
