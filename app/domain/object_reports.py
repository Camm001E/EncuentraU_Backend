from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.domain.report_images import ImageReference


class ReportType(StrEnum):
    LOST = "lost"
    FOUND = "found"


class ReportStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class AnalysisConfidence(StrEnum):
    LOW = "baja"
    MEDIUM = "media"
    HIGH = "alta"


class ReportError(Exception):
    message = "No se pudo completar la operación del reporte."


class ReportValidationError(ReportError, ValueError):
    message = "Los datos del reporte no son válidos."


class ReportNotFoundError(ReportError):
    message = "Reporte no encontrado."


class ReportConflictError(ReportError):
    message = "El reporte cambió. Vuelve a consultarlo antes de modificarlo."


class ReportNotActiveError(ReportConflictError):
    message = "Solo los reportes activos se pueden editar o cancelar."


class ReportPersistenceError(ReportError):
    message = "El servicio de reportes no está disponible."


TEXT_LIMITS = {
    "object_type": 200,
    "category": 100,
    "primary_color": 100,
    "brand": 100,
    "shape": 500,
    "description": 5000,
    "location": 300,
    "private_feature": 2000,
}
NULLABLE_FIELDS = frozenset({"primary_color", "brand", "shape", "private_feature"})
MAX_COLORS = 20
MAX_ANALYSIS_BYTES = 65536
_LOCAL_OR_BINARY = re.compile(r"(?i)(?:(?<![a-z])[a-z]:[\\/]|file://|data:|^/|^\\\\)")
_BINARY_FIELDS = frozenset(
    {
        "image",
        "image_base64",
        "image_bytes",
        "image_data",
        "file_bytes",
        "local_path",
        "image_path",
        "file_path",
    }
)


def normalize_text(value: str) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ReportValidationError
    return " ".join(unicodedata.normalize("NFC", value).split())


def normalize_color(value: str) -> str:
    return normalize_text(value).casefold()


def validate_event_date(value: date) -> date:
    if type(value) is not date or value > date.today():
        raise ReportValidationError("La fecha del evento no puede ser futura.")
    return value


def validate_extracted_data(value: dict[str, Any]) -> dict[str, Any]:
    """Preserve JSON values; never accept image bytes, data URIs or local paths."""

    def check(item: Any, depth: int = 0) -> None:
        if depth > 20:
            raise ReportValidationError
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ReportValidationError
                if key.casefold() in _BINARY_FIELDS:
                    raise ReportValidationError
                check(key, depth + 1)
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
        elif isinstance(item, str):
            if "\x00" in item or _LOCAL_OR_BINARY.search(item):
                raise ReportValidationError
        elif item is not None and type(item) not in (int, float, bool):
            raise ReportValidationError

    if not isinstance(value, dict):
        raise ReportValidationError
    check(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_ANALYSIS_BYTES:
            raise ReportValidationError
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError):
        raise ReportValidationError from None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportAttributes:
    object_type: str
    category: str
    description: str
    location: str
    event_date: date
    primary_color: str | None = None
    secondary_colors: tuple[str, ...] = ()
    brand: str | None = None
    shape: str | None = None
    private_feature: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name, maximum in TEXT_LIMITS.items():
            raw = getattr(self, name)
            if raw is None and name in NULLABLE_FIELDS:
                continue
            value = normalize_text(raw)
            if name in {"object_type", "category", "primary_color"}:
                value = value.casefold()
            if not value and name in NULLABLE_FIELDS:
                value = None
            elif not value or len(value) > maximum:
                raise ReportValidationError
            if value is not None and _LOCAL_OR_BINARY.search(value):
                raise ReportValidationError
            object.__setattr__(self, name, value)
        if not isinstance(self.secondary_colors, (list, tuple)):
            raise ReportValidationError
        if len(self.secondary_colors) > MAX_COLORS:
            raise ReportValidationError
        colors = []
        for raw in self.secondary_colors:
            color = normalize_color(raw)
            if len(color) > TEXT_LIMITS["primary_color"]:
                raise ReportValidationError
            if _LOCAL_OR_BINARY.search(color):
                raise ReportValidationError
            if color and color != self.primary_color and color not in colors:
                colors.append(color)
        object.__setattr__(self, "secondary_colors", tuple(colors))
        validate_event_date(self.event_date)


ATTRIBUTE_FIELDS = frozenset(item.name for item in fields(ReportAttributes))
EDITABLE_FIELDS = ATTRIBUTE_FIELDS | {"status"}


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisData:
    extracted_data: dict[str, Any] = field(repr=False)
    confidence: AnalysisConfidence

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "extracted_data", validate_extracted_data(self.extracted_data)
        )
        try:
            confidence = AnalysisConfidence(self.confidence)
        except ValueError:
            raise ReportValidationError from None
        object.__setattr__(self, "confidence", confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageAnalysis:
    id: UUID
    report_id: UUID
    provider: str
    model: str
    data: AnalysisData
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObjectReport:
    id: UUID
    user_id: UUID
    report_type: ReportType
    attributes: ReportAttributes
    status: ReportStatus = ReportStatus.ACTIVE
    analysis: ImageAnalysis | None = None
    image: ImageReference | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    evidence_locked: bool = False


@dataclass(frozen=True, slots=True)
class ReportPage:
    items: tuple[ObjectReport, ...]
    total: int
    limit: int
    offset: int
