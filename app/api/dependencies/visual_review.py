from typing import Annotated

from fastapi import Depends

from app.application.visual_review import VisualReviewCache
from app.core.config import Settings, get_settings
from app.infrastructure.visual_pair_analyzer import VisualPairAnalyzer

_CACHE = VisualReviewCache()


def get_visual_review_cache():
    return _CACHE


def get_visual_pair_analyzer(settings: Annotated[Settings, Depends(get_settings)]):
    return VisualPairAnalyzer(settings)
