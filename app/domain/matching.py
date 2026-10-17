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
    SHAPE = "shape"
    VISUAL_FEATURES = "visual_features"
    LOCATION = "location"
    DATE = "date"
    DESCRIPTION = "description"


class MatchFactorGroup(StrEnum):
    IDENTITY = "identity"
    CONTEXT = "context"


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
    description: str | None = Field(default=None, max_length=5000)


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lost: MatchableObject
    found: MatchableObject


class MatchFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: MatchFactorName
    group: MatchFactorGroup
    label: str
    weight: int = Field(ge=0, le=100)
    evaluable_weight: float = Field(
        ge=0,
        le=100,
        description="Peso interno respaldado por datos comparables en ambos objetos.",
    )
    score: float = Field(ge=0, le=100)
    status: MatchFactorStatus
    explanation: str


class MatchEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    percentage: int = Field(ge=0, le=100)
    identity_percentage: float = Field(ge=0, le=100)
    context_percentage: float = Field(ge=0, le=100)
    evidence_coverage: float = Field(
        ge=0, le=100, description="Porcentaje del modelo que se pudo evaluar."
    )
    compatible: bool
    level: MatchLevel
    factors: list[MatchFactor]
    warnings: list[str] = Field(default_factory=list)
