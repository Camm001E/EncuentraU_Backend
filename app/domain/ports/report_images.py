from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from app.domain.report_images import ImageAccess, ProcessedImage, ReportImage


class ImageStorage(Protocol):
    def write(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class ImageProcessor(Protocol):
    def process(
        self, data: bytes, filename: str, content_type: str
    ) -> ProcessedImage: ...


class ReportImageRepository(Protocol):
    def transaction(
        self, report_id: UUID, user_id: UUID, *, write: bool = False
    ) -> AbstractContextManager[ImageAccess | None]:
        """Serialize mutations and protect content reads against replacement."""
        ...

    def save(self, image: ReportImage) -> None: ...
    def delete(self, report_id: UUID) -> None: ...
