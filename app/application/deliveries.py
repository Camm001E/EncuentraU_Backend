from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.deliveries import (
    MAX_DELIVERY_NOTE_LENGTH,
    MIN_DISPUTE_LENGTH,
    DeliveryEvent,
    DeliveryEventType,
)
from app.domain.ownership import (
    WorkflowNotFound,
    require_admin,
    validate_page,
    validate_text,
)
from app.domain.ports.deliveries import DeliveryRepository
from app.domain.users import User


class DeliveryUseCase:
    def __init__(self, repository: DeliveryRepository):
        self.repository = repository

    def get(self, user: User, *, admin=False, **identifier):
        if admin:
            require_admin(user)
        context = self.repository.get(**identifier)
        if context is None:
            raise WorkflowNotFound
        if not admin:
            context.relationship(user)
        return context


class GetDelivery(DeliveryUseCase):
    def __call__(self, user: User, *, conversation_id: UUID):
        return self.get(user, conversation_id=conversation_id)


class GetAdminDelivery(DeliveryUseCase):
    def __call__(self, delivery_id: UUID, user: User):
        return self.get(user, admin=True, delivery_id=delivery_id)


class ListMyDeliveries(DeliveryUseCase):
    def __call__(self, user: User, *, status=None, limit=20, offset=0):
        validate_page(limit, offset)
        if not user.is_active:
            raise WorkflowNotFound
        return self.repository.list(
            user_id=user.id, status=status, limit=limit, offset=offset
        )


class ListAdminDeliveries(ListMyDeliveries):
    def __call__(self, user: User, *, status=None, limit=20, offset=0):
        require_admin(user)
        validate_page(limit, offset)
        return self.repository.list(
            user_id=None, status=status, limit=limit, offset=offset
        )


class ListDeliveryEvents(DeliveryUseCase):
    def __call__(self, delivery_id: UUID, user: User):
        return self.get(user, admin=user.role.value == "admin", delivery_id=delivery_id)


class ChangeDelivery(DeliveryUseCase):
    def change(self, delivery_id, user, operation, note=None):
        admin = operation in (
            DeliveryEventType.ADMIN_COMPLETED,
            DeliveryEventType.ADMIN_REOPENED,
        )
        if admin:
            require_admin(user)
        with self.repository.transaction(delivery_id) as context:
            if context is None:
                raise WorkflowNotFound
            relationship = None if admin else context.relationship(user)
            context.validate_active_case()
            now = datetime.now(UTC)
            current = context.delivery
            if operation is None:
                updated = current.confirm(relationship, now)
                operation = DeliveryEventType(f"{relationship}_confirmed")
            elif operation == DeliveryEventType.DISPUTE_OPENED:
                updated = current.dispute(user.id, note, now)
            elif operation == DeliveryEventType.ADMIN_REOPENED:
                updated = current.reopen(user, note, now)
            else:
                updated = current.complete(user, note, now)
            if updated != current:
                self.repository.save(
                    updated,
                    DeliveryEvent(
                        uuid4(),
                        current.id,
                        user.id,
                        operation,
                        note,
                        now,
                    ),
                    close=operation == DeliveryEventType.ADMIN_COMPLETED,
                )
        return self.repository.get(delivery_id=delivery_id)


class ConfirmDelivery(ChangeDelivery):
    def __call__(self, delivery_id: UUID, user: User):
        return self.change(delivery_id, user, None)


class OpenDeliveryDispute(ChangeDelivery):
    def __call__(self, delivery_id: UUID, user: User, reason: str):
        reason = validate_text(reason, MIN_DISPUTE_LENGTH, MAX_DELIVERY_NOTE_LENGTH)
        return self.change(delivery_id, user, DeliveryEventType.DISPUTE_OPENED, reason)


class ReopenDelivery(ChangeDelivery):
    def __call__(self, delivery_id: UUID, user: User, admin_note: str):
        note = validate_text(admin_note, 1, MAX_DELIVERY_NOTE_LENGTH)
        return self.change(delivery_id, user, DeliveryEventType.ADMIN_REOPENED, note)


class CompleteDelivery(ChangeDelivery):
    def __call__(self, delivery_id: UUID, user: User, admin_note: str | None = None):
        note = (
            validate_text(admin_note, 1, MAX_DELIVERY_NOTE_LENGTH)
            if admin_note
            else None
        )
        return self.change(delivery_id, user, DeliveryEventType.ADMIN_COMPLETED, note)
