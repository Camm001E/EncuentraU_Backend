from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.report_images import ImageReference


class ReportImageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    report_id: UUID
    content_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_reference(cls, image: ImageReference) -> "ReportImageResponse":
        return cls(**asdict(image))
