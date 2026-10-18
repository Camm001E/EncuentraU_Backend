from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from uuid import UUID, uuid4

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.deliveries import (
    Delivery,
    DeliveryContext,
    DeliveryEvent,
    DeliveryEventType,
    DeliveryStatus,
)
from app.domain.ownership import (
    ConversationStatus,
    WorkflowPage,
    WorkflowUnavailable,
    aware,
)
from app.infrastructure.database.evidence_guard import workflow_gate
from app.infrastructure.database.models import (
    Conversation,
    Message,
    ObjectReport,
    OwnershipClaim,
)
from app.infrastructure.database.models import (
    Delivery as DeliveryModel,
)
from app.infrastructure.database.models import (
    DeliveryEvent as EventModel,
)
from app.infrastructure.database.ownership_repository import (
    SQLAlchemyOwnershipClaimRepository,
    controlled,
)


def add_delivery(session, claim, conversation_id):
    """Called inside approval; never commits a partial approval/conversation."""
    identifier = uuid4()
    session.add(
        DeliveryModel(
            id=identifier,
            match_id=claim.match_id,
            claim_id=claim.id,
            conversation_id=conversation_id,
            status="coordinating",
            created_at=claim.updated_at,
            updated_at=claim.updated_at,
        )
    )
    session.flush()
    session.add(
        EventModel(
            id=uuid4(),
            delivery_id=identifier,
            actor_user_id=claim.admin_id,
            event_type="delivery_created",
            created_at=claim.updated_at,
        )
    )
    session.flush()


def entity(model, cls):
    values = {key: getattr(model, key) for key in cls.__dataclass_fields__}
    for key, value in values.items():
        if value is not None and (key.endswith("_at")):
            values[key] = aware(value)
    if cls is Delivery:
        values["status"] = DeliveryStatus(values["status"])
    else:
        values["event_type"] = DeliveryEventType(values["event_type"])
    return cls(**values)


class SQLAlchemyDeliveryRepository:
    def __init__(self, session: Session):
        self.session = session

    @controlled
    def get(
        self, *, delivery_id: UUID | None = None, conversation_id: UUID | None = None
    ):
        query = select(DeliveryModel).execution_options(populate_existing=True)
        if delivery_id is not None:
            query = query.where(DeliveryModel.id == delivery_id)
        elif conversation_id is not None:
            query = query.where(DeliveryModel.conversation_id == conversation_id)
        else:
            return None
        model = self.session.scalar(query)
        if model is None:
            return None
        context = SQLAlchemyOwnershipClaimRepository(self.session).get_context(
            claim_id=model.claim_id
        )
        conversation = self.session.get(Conversation, model.conversation_id)
        events = self.session.scalars(
            select(EventModel)
            .where(EventModel.delivery_id == model.id)
            .order_by(EventModel.created_at, EventModel.id)
        ).all()
        count, latest = self.session.execute(
            select(func.count(Message.id), func.max(Message.created_at)).where(
                Message.conversation_id == model.conversation_id
            )
        ).one()
        return DeliveryContext(
            entity(model, Delivery),
            context,
            ConversationStatus(conversation.status),
            tuple(entity(e, DeliveryEvent) for e in events),
            count,
            aware(latest) if latest else None,
        )

    @contextmanager
    def transaction(self, delivery_id) -> Iterator[DeliveryContext | None]:
        try:
            workflow_gate(self.session)
            model = self.session.scalar(
                select(DeliveryModel)
                .where(DeliveryModel.id == delivery_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if model is not None:
                # Sending a message and closing the conversation use the same row lock.
                self.session.scalar(
                    select(Conversation)
                    .where(Conversation.id == model.conversation_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            yield self.get(delivery_id=delivery_id) if model else None
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise WorkflowUnavailable from None
        except Exception:
            self.session.rollback()
            raise

    @controlled
    def list(self, *, user_id, status, limit, offset):
        query = select(DeliveryModel.id).join(
            OwnershipClaim, OwnershipClaim.id == DeliveryModel.claim_id
        )
        if user_id is not None:
            query = query.where(
                or_(
                    OwnershipClaim.claimant_user_id == user_id,
                    OwnershipClaim.custodian_user_id == user_id,
                )
            )
        if status is not None:
            query = query.where(DeliveryModel.status == status)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        priority = case(
            {
                "disputed": 0,
                "awaiting_admin": 1,
                "awaiting_confirmations": 2,
                "coordinating": 3,
                "completed": 4,
            },
            value=DeliveryModel.status,
        )
        order = (
            (priority, DeliveryModel.created_at, DeliveryModel.id)
            if user_id is None
            else (DeliveryModel.updated_at.desc(), DeliveryModel.id.desc())
        )
        ids = self.session.scalars(
            query.order_by(*order).limit(limit).offset(offset)
        ).all()
        return WorkflowPage(
            tuple(self.get(delivery_id=id_) for id_ in ids), total, limit, offset
        )

    @controlled
    def save(self, delivery, event, *, close=False):
        model = self.session.get(DeliveryModel, delivery.id)
        for key, value in asdict(delivery).items():
            setattr(model, key, value)
        if close:
            context = SQLAlchemyOwnershipClaimRepository(self.session).get_context(
                claim_id=delivery.claim_id
            )
            for report in (context.match.my_report, context.match.candidate_report):
                record = self.session.get(ObjectReport, report.id)
                record.status = "resolved"
                record.updated_at = delivery.updated_at
            conversation = self.session.get(Conversation, delivery.conversation_id)
            conversation.status = "closed"
            conversation.updated_at = delivery.updated_at
        self.session.add(EventModel(**asdict(event)))
        self.session.flush()
