from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from app.domain.deliveries import (
    Delivery,
    DeliveryContext,
    DeliveryEvent,
    DeliveryStatus,
)
from app.domain.ownership import WorkflowPage


class DeliveryRepository(Protocol):
    def get(
        self, *, delivery_id: UUID | None = None, conversation_id: UUID | None = None
    ) -> DeliveryContext | None: ...
    def transaction(
        self, delivery_id: UUID
    ) -> AbstractContextManager[DeliveryContext | None]: ...
    def list(
        self,
        *,
        user_id: UUID | None,
        status: DeliveryStatus | None,
        limit: int,
        offset: int,
    ) -> WorkflowPage[DeliveryContext]: ...
    def save(
        self, delivery: Delivery, event: DeliveryEvent, *, close: bool = False
    ) -> None: ...
