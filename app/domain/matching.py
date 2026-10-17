from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MatchLevel(StrEnum):
    HIGH = "high"
    POSSIBLE = "possible"
    LOW = "low"


class MatchFactorName(StrEnum):
    OBJECT_TYPE = "object_type"
    CATEGORY = "category"
    COLOR = "color"
    BRAND = "brand"
    VISUAL_FEATURES = "visual_features"
    LOCATION = "location"
    DATE = "date"
    DESCRIPTION = "description"


class MatchFactorStatus(StrEnum):
    MATCH = "match"
    PARTIAL = "partial"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


class MatchableObject(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    object_type: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    primary_color: str | None = Field(default=None, max_length=100)
    secondary_colors: list[str] = Field(default_factory=list, max_length=20)
    brand: str | None = Field(default=None, max_length=100)
    shape: str | None = Field(default=None, max_length=500)
    visible_features: list[str] = Field(default_factory=list, max_length=50)
    visible_text: list[str] = Field(default_factory=list, max_length=50)
    location: str | None = Field(default=None, max_length=300)
    event_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lost: MatchableObject
    found: MatchableObject


class MatchFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: MatchFactorName
    label: str
    weight: int = Field(ge=0, le=100)
    score: float = Field(ge=0, le=100)
    status: MatchFactorStatus
    explanation: str


class MatchEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    percentage: int = Field(ge=0, le=100)
    level: MatchLevel
    factors: list[MatchFactor]
    warnings: list[str] = Field(default_factory=list)
