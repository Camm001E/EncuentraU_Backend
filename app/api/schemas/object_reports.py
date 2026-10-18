from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.api.schemas.report_images import ReportImageResponse
from app.domain.object_reports import (
    MAX_COLORS,
    NULLABLE_FIELDS,
    TEXT_LIMITS,
    AnalysisConfidence,
    AnalysisData,
    ObjectReport,
    ReportAttributes,
    ReportPage,
    ReportStatus,
    ReportType,
    normalize_text,
    validate_event_date,
    validate_extracted_data,
)


class ReportInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, allow_inf_nan=False
    )

    @field_validator(
        "object_type",
        "category",
        "primary_color",
        "brand",
        "shape",
        "description",
        "location",
        "private_feature",
        check_fields=False,
        mode="before",
    )
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        return normalize_text(value) if isinstance(value, str) else value

    @field_validator("event_date", check_fields=False)
    @classmethod
    def no_future_dates(cls, value: date | None) -> date | None:
        return validate_event_date(value) if value is not None else None


class AnalysisCreate(ReportInput):
    extracted_data: dict[str, JsonValue]
    confidence: AnalysisConfidence

    @field_validator("extracted_data")
    @classmethod
    def valid_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_extracted_data(value)

    def to_domain(self) -> AnalysisData:
        return AnalysisData(
            extracted_data=self.extracted_data, confidence=self.confidence
        )


Color = Annotated[str, Field(min_length=1, max_length=TEXT_LIMITS["primary_color"])]


class ReportCreate(ReportInput):
    report_type: ReportType
    object_type: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    primary_color: str | None = Field(default=None, max_length=100)
    secondary_colors: list[Color] = Field(default_factory=list, max_length=MAX_COLORS)
    brand: str | None = Field(default=None, max_length=100)
    shape: str | None = Field(default=None, max_length=500)
    description: str = Field(min_length=1, max_length=5000)
    location: str = Field(min_length=1, max_length=300)
    event_date: date
    private_feature: str | None = Field(default=None, max_length=2000)
    analysis: AnalysisCreate | None = None

    def to_attributes(self) -> ReportAttributes:
        return ReportAttributes(**self.model_dump(exclude={"analysis", "report_type"}))


class ReportUpdate(ReportInput):
    object_type: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    primary_color: str | None = Field(default=None, max_length=100)
    secondary_colors: list[Color] | None = Field(default=None, max_length=MAX_COLORS)
    brand: str | None = Field(default=None, max_length=100)
    shape: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    location: str | None = Field(default=None, min_length=1, max_length=300)
    event_date: date | None = None
    private_feature: str | None = Field(default=None, max_length=2000)
    status: ReportStatus | None = None

    @model_validator(mode="after")
    def valid_partial_update(self) -> ReportUpdate:
        if not self.model_fields_set:
            raise ValueError("Envía al menos un campo editable.")
        for name in self.model_fields_set - NULLABLE_FIELDS:
            if getattr(self, name) is None:
                raise ValueError("Un campo obligatorio no puede ser null.")
        return self


class AnalysisResponse(BaseModel):
    id: UUID
    report_id: UUID
    provider: str
    model: str
    extracted_data: dict[str, JsonValue]
    confidence: AnalysisConfidence
    created_at: datetime


class ReportResponse(BaseModel):
    id: UUID
    user_id: UUID
    report_type: ReportType
    status: ReportStatus
    object_type: str
    category: str
    primary_color: str | None
    secondary_colors: list[str]
    brand: str | None
    shape: str | None
    description: str
    location: str
    event_date: date
    private_feature: str | None
    analysis: AnalysisResponse | None
    image: ReportImageResponse | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_report(cls, report: ObjectReport) -> ReportResponse:
        analysis = report.analysis
        return cls(
            id=report.id,
            user_id=report.user_id,
            report_type=report.report_type,
            status=report.status,
            **asdict(report.attributes),
            created_at=report.created_at,
            updated_at=report.updated_at,
            image=ReportImageResponse.from_reference(report.image)
            if report.image
            else None,
            analysis=(
                AnalysisResponse(
                    id=analysis.id,
                    report_id=analysis.report_id,
                    provider=analysis.provider,
                    model=analysis.model,
                    extracted_data=analysis.data.extracted_data,
                    confidence=analysis.data.confidence,
                    created_at=analysis.created_at,
                )
                if analysis is not None
                else None
            ),
        )


class ReportListResponse(BaseModel):
    items: list[ReportResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: ReportPage) -> ReportListResponse:
        return cls(
            items=[ReportResponse.from_report(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
