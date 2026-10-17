from fastapi import APIRouter

from app.application.matching_service import MatchingService
from app.domain.matching import MatchEvaluation, MatchRequest

router = APIRouter(prefix="/matches", tags=["matching"])
matching_service = MatchingService()


@router.post(
    "/evaluate",
    response_model=MatchEvaluation,
    summary="Evaluar la coincidencia entre dos objetos",
)
def evaluate_match(request: MatchRequest) -> MatchEvaluation:
    return matching_service.evaluate(request)
