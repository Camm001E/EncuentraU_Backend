from uuid import UUID

from app.domain.ownership import (
    MAX_MESSAGE_LENGTH,
    MessageCursor,
    WorkflowNotFound,
    validate_page,
    validate_text,
)
from app.domain.ports.ownership import ConversationRepository
from app.domain.users import User


class ConversationUseCase:
    def __init__(self, repository: ConversationRepository):
        self.repository = repository

    def authorize(self, conversation_id: UUID, user: User):
        access = self.repository.get_access(conversation_id)
        if access is None:
            raise WorkflowNotFound
        access.authorize(user)
        return access


class ListConversations(ConversationUseCase):
    def __call__(self, user: User, *, limit: int = 20, offset: int = 0):
        validate_page(limit, offset)
        if not user.is_active:
            raise WorkflowNotFound
        return self.repository.list_by_user(user.id, limit=limit, offset=offset)


class GetConversation(ConversationUseCase):
    def __call__(self, conversation_id: UUID, user: User):
        self.authorize(conversation_id, user)
        return self.repository.get_view(conversation_id, user.id)


class ListMessages(ConversationUseCase):
    def __call__(
        self,
        conversation_id: UUID,
        user: User,
        *,
        limit: int = 50,
        before: str | None = None,
    ):
        self.authorize(conversation_id, user)
        validate_page(limit, 0)
        return self.repository.list_messages(
            conversation_id, user.id, limit=limit, before=MessageCursor.decode(before)
        )


class SendMessage(ConversationUseCase):
    def __call__(
        self, conversation_id: UUID, user: User, body: str, client_message_id: UUID
    ):
        body = validate_text(body, 1, MAX_MESSAGE_LENGTH)
        with self.repository.transaction(conversation_id) as access:
            if access is None:
                raise WorkflowNotFound
            access.authorize(user)
            return self.repository.send(
                conversation_id, user.id, body, client_message_id
            )


class MarkConversationRead(ConversationUseCase):
    def __call__(
        self, conversation_id: UUID, user: User, last_message_id: UUID | None = None
    ):
        with self.repository.transaction(conversation_id) as access:
            if access is None:
                raise WorkflowNotFound
            access.authorize(user)
            self.repository.mark_read(conversation_id, user.id, last_message_id)
