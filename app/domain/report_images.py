from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class ReportImageError(Exception):
    message = "No se pudo completar la operación de fotografía."


class ImageNotFoundError(ReportImageError):
    message = "Fotografía no encontrada."


class ImageValidationError(ReportImageError):
    message = "La fotografía está vacía, dañada o no es válida."


class ImageTypeError(ImageValidationError):
    message = "Usa una fotografía JPEG, PNG o WebP con su formato correcto."


class ImageTooLargeError(ImageValidationError):
    message = "La fotografía supera el tamaño permitido."


class ImageDimensionsError(ImageValidationError):
    message = "La fotografía tiene dimensiones excesivas."


class ImageUnavailableError(ReportImageError):
    message = "El servicio de fotografías no está disponible temporalmente."


@dataclass(frozen=True, slots=True)
class ImageReference:
    """Public metadata; never contains storage paths or client filenames."""

    id: UUID
    report_id: UUID
    content_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReportImage:
    reference: ImageReference
    storage_key: str = field(repr=False)
    original_filename: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    data: bytes = field(repr=False)
    content_type: str
    extension: str
    original_filename: str
    sha256: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ImageAccess:
    owner_id: UUID
    status: str
    participant: bool
    image: ReportImage | None


@dataclass(frozen=True, slots=True)
class ImageContent:
    data: bytes = field(repr=False)
    reference: ImageReference
