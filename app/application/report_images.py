import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.authentication import InactiveUserError
from app.domain.object_reports import ReportNotActiveError, ReportStatus
from app.domain.ports.report_images import (
    ImageProcessor,
    ImageStorage,
    ReportImageRepository,
)
from app.domain.report_images import (
    ImageAccess,
    ImageContent,
    ImageNotFoundError,
    ImageReference,
    ImageUnavailableError,
    ReportImage,
)
from app.domain.users import User, UserRole

logger = logging.getLogger(__name__)


class ReportImageService:
    def __init__(
        self,
        repository: ReportImageRepository,
        storage: ImageStorage,
        processor: ImageProcessor,
    ):
        self.repository = repository
        self.storage = storage
        self.processor = processor

    @staticmethod
    def _authorize(
        access: ImageAccess | None, user: User, *, write: bool
    ) -> ImageAccess:
        if not user.is_active:
            raise InactiveUserError
        if access is None:
            raise ImageNotFoundError
        if write:
            if access.owner_id != user.id:
                raise ImageNotFoundError
            if access.status != ReportStatus.ACTIVE:
                raise ReportNotActiveError
        elif (
            access.owner_id != user.id
            and not access.participant
            and user.role != UserRole.ADMIN
        ):
            raise ImageNotFoundError
        return access

    def _discard(self, key: str) -> None:
        try:
            self.storage.delete(key)
        except ImageUnavailableError:
            # Never expose a path/key, or lose the current photo because cleanup
            # of an obsolete object failed. It remains inaccessible via the API.
            logger.warning("No se pudo retirar un archivo de fotografía obsoleto.")

    def upload(
        self, report_id: UUID, user: User, data: bytes, filename: str, content_type: str
    ) -> ImageReference:
        new_key = None
        previous = None
        try:
            with self.repository.transaction(report_id, user.id, write=True) as access:
                access = self._authorize(access, user, write=True)
                processed = self.processor.process(data, filename, content_type)
                previous = access.image
                candidate_key = f"{uuid4().hex}.{processed.extension}"
                self.storage.write(candidate_key, processed.data)
                # Compensate only an object this operation actually wrote.
                new_key = candidate_key
                now = datetime.now(UTC)
                reference = ImageReference(
                    id=previous.reference.id if previous else uuid4(),
                    report_id=report_id,
                    content_type=processed.content_type,
                    size_bytes=len(processed.data),
                    sha256=processed.sha256,
                    width=processed.width,
                    height=processed.height,
                    created_at=previous.reference.created_at if previous else now,
                    updated_at=now,
                )
                self.repository.save(
                    ReportImage(reference, new_key, processed.original_filename)
                )
        except Exception:
            if new_key is not None:
                self._discard(new_key)
            raise
        if previous is not None:
            self._discard(previous.storage_key)
        return reference

    def metadata(self, report_id: UUID, user: User) -> ImageReference:
        with self.repository.transaction(report_id, user.id) as access:
            access = self._authorize(access, user, write=False)
            if access.image is None:
                raise ImageNotFoundError
            return access.image.reference

    def content(self, report_id: UUID, user: User) -> ImageContent:
        with self.repository.transaction(report_id, user.id) as access:
            access = self._authorize(access, user, write=False)
            if access.image is None:
                raise ImageNotFoundError
            data = self.storage.read(access.image.storage_key)
            reference = access.image.reference
            if (
                len(data) != reference.size_bytes
                or hashlib.sha256(data).hexdigest() != reference.sha256
            ):
                raise ImageUnavailableError
            return ImageContent(data, reference)

    def delete(self, report_id: UUID, user: User) -> None:
        with self.repository.transaction(report_id, user.id, write=True) as access:
            access = self._authorize(access, user, write=True)
            previous = access.image
            if previous is None:
                raise ImageNotFoundError
            self.repository.delete(report_id)
        self._discard(previous.storage_key)
