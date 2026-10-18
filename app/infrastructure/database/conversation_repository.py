from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased, selectinload

from app.domain.ownership import (
    ClaimStatus,
    ConversationAccess,
    ConversationStatus,
    ConversationView,
    MessageCursor,
    MessagePage,
    WorkflowConflict,
    WorkflowNotFound,
    WorkflowPage,
    WorkflowUnavailable,
    aware,
    display_name,
)
from app.domain.ownership import (
    Message as MessageEntity,
)
from app.infrastructure.database.models import (
    Conversation,
    ConversationParticipant,
    Message,
    ObjectMatch,
    ObjectReport,
    OwnershipClaim,
    User,
)
from app.infrastructure.database.object_match_repository import (
    SQLAlchemyObjectMatchRepository,
)
from app.infrastructure.database.ownership_repository import controlled


class SQLAlchemyConversationRepository:
    def __init__(self, session: Session):
        self.session = session

    def now(self) -> datetime:
        if self.session.get_bind().dialect.name == "postgresql":
            return self.session.scalar(select(func.clock_timestamp()))
        return datetime.now(UTC)

    @controlled
    def get_access(self, conversation_id: UUID) -> ConversationAccess | None:
        row = self.session.execute(
            select(Conversation, OwnershipClaim.status, ObjectMatch.status)
            .join(OwnershipClaim, Conversation.claim_id == OwnershipClaim.id)
            .join(ObjectMatch, Conversation.match_id == ObjectMatch.id)
            .where(Conversation.id == conversation_id)
            .execution_options(populate_existing=True)
        ).first()
        if row is None:
            return None
        conversation, claim_status, match_status = row
        participants = tuple(
            self.session.scalars(
                select(ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id == conversation_id
                )
            ).all()
        )
        return ConversationAccess(
            conversation.id,
            conversation.match_id,
            conversation.claim_id,
            ConversationStatus(conversation.status),
            participants,
            claim_status == ClaimStatus.APPROVED
            and match_status == "accepted"
            and len(participants) == 2,
        )

    @contextmanager
    def transaction(self, conversation_id: UUID) -> Iterator[ConversationAccess | None]:
        try:
            self.session.scalar(
                select(Conversation)
                .where(Conversation.id == conversation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            yield self.get_access(conversation_id)
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise WorkflowUnavailable from None
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def message_view(row: Message, user_id: UUID) -> MessageEntity:
        return MessageEntity(
            row.id,
            row.client_message_id,
            row.body,
            row.sender_id == user_id,
            aware(row.created_at),
        )

    @controlled
    def list_by_user(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> WorkflowPage[ConversationView]:
        participant = ConversationParticipant
        query = select(Conversation.id).join(
            participant, participant.conversation_id == Conversation.id
        )
        query = query.join(
            OwnershipClaim, Conversation.claim_id == OwnershipClaim.id
        ).join(ObjectMatch, Conversation.match_id == ObjectMatch.id)
        query = query.where(
            participant.user_id == user_id,
            Conversation.status == "active",
            OwnershipClaim.status == "approved",
            ObjectMatch.status == "accepted",
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        ids = self.session.scalars(
            query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return WorkflowPage(
            tuple(self.get_view(identifier, user_id) for identifier in ids),
            total,
            limit,
            offset,
        )

    @controlled
    def get_view(self, conversation_id: UUID, user_id: UUID) -> ConversationView:
        # Explicit membership, including calls made directly by repository consumers.
        mine, other = aliased(ConversationParticipant), aliased(ConversationParticipant)
        row = self.session.execute(
            select(Conversation, mine.last_read_at, User.full_name, ObjectReport)
            .join(
                mine,
                and_(mine.conversation_id == Conversation.id, mine.user_id == user_id),
            )
            .join(
                other,
                and_(
                    other.conversation_id == Conversation.id, other.user_id != user_id
                ),
            )
            .join(User, User.id == other.user_id)
            .join(ObjectMatch, ObjectMatch.id == Conversation.match_id)
            .join(ObjectReport, ObjectReport.id == ObjectMatch.lost_report_id)
            .where(Conversation.id == conversation_id)
            .options(selectinload(ObjectReport.image))
        ).first()
        if row is None:
            raise WorkflowNotFound
        conversation, read_at, name, report = row
        latest = self.session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        unread = (
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id, Message.sender_id != user_id
            )
        )
        if read_at is not None:
            unread = unread.where(Message.created_at > read_at)
        return ConversationView(
            conversation.id,
            conversation.match_id,
            conversation.claim_id,
            ConversationStatus(conversation.status),
            display_name(name),
            SQLAlchemyObjectMatchRepository._summary(report),
            self.message_view(latest, user_id) if latest else None,
            aware(latest.created_at) if latest else None,
            self.session.scalar(unread),
            aware(conversation.created_at),
            aware(conversation.updated_at),
        )

    @controlled
    def list_messages(
        self,
        conversation_id: UUID,
        user_id: UUID,
        *,
        limit: int,
        before: MessageCursor | None,
    ) -> MessagePage:
        query = select(Message).where(Message.conversation_id == conversation_id)
        if before is not None:
            query = query.where(
                or_(
                    Message.created_at < before.created_at,
                    and_(
                        Message.created_at == before.created_at, Message.id < before.id
                    ),
                )
            )
        rows = self.session.scalars(
            query.order_by(Message.created_at.desc(), Message.id.desc()).limit(
                limit + 1
            )
        ).all()
        more = len(rows) > limit
        rows = rows[:limit]
        cursor = (
            MessageCursor(aware(rows[-1].created_at), rows[-1].id).encode()
            if more
            else None
        )
        return MessagePage(
            tuple(self.message_view(row, user_id) for row in reversed(rows)),
            cursor,
            limit,
        )

    @controlled
    def send(
        self, conversation_id: UUID, user_id: UUID, body: str, client_message_id: UUID
    ) -> MessageEntity:
        existing = self.session.scalar(
            select(Message).where(
                Message.sender_id == user_id,
                Message.client_message_id == client_message_id,
            )
        )
        if existing is not None:
            if existing.conversation_id != conversation_id or existing.body != body:
                raise WorkflowConflict
            return self.message_view(existing, user_id)
        now = self.now()
        model = Message(
            id=uuid4(),
            conversation_id=conversation_id,
            sender_id=user_id,
            body=body,
            client_message_id=client_message_id,
            created_at=now,
        )
        self.session.add(model)
        self.session.get(Conversation, conversation_id).updated_at = now
        self.session.flush()
        return self.message_view(model, user_id)

    @controlled
    def mark_read(
        self, conversation_id: UUID, user_id: UUID, last_message_id: UUID | None
    ) -> None:
        timestamp = self.now()
        if last_message_id is not None:
            message = self.session.scalar(
                select(Message).where(
                    Message.id == last_message_id,
                    Message.conversation_id == conversation_id,
                )
            )
            if message is None:
                raise WorkflowNotFound
            timestamp = aware(message.created_at)
        participant = self.session.get(
            ConversationParticipant, (conversation_id, user_id)
        )
        if participant.last_read_at is None or aware(participant.last_read_at) < aware(
            timestamp
        ):
            participant.last_read_at = timestamp
        self.session.flush()
