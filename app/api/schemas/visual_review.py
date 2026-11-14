from typing import Literal

from pydantic import BaseModel, Field

from app.domain.visual_comparison import VisualComparison


class VisualReviewResponse(BaseModel):
    comparison: VisualComparison
    provider: Literal["openai", "gemini", "local"]
    model: str
    prompt_version: str
    fallback_used: bool
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cached: bool
    verification: Literal["not_needed", "confirmed", "unconfirmed", "unavailable"]
