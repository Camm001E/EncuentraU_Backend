from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from app.domain.ownership import (
    ClaimContext,
    ClaimStatus,
    ConversationAccess,
    ConversationView,
    Message,
    MessageCursor,
    MessagePage,
    OwnershipClaim,
    WorkflowPage,
)


class OwnershipClaimRepository(Protocol):
    def transaction(
        self, *, match_id: UUID | None = None, claim_id: UUID | None = None
    ) -> AbstractContextManager[ClaimContext | None]: ...
    def get_context(
        self, *, match_id: UUID | None = None, claim_id: UUID | None = None
    ) -> ClaimContext | None: ...
    def add(self, claim: OwnershipClaim) -> None: ...
    def list_contexts(
        self,
        *,
        user_id: UUID | None,
        status: ClaimStatus | None,
        limit: int,
        offset: int,
    ) -> WorkflowPage[ClaimContext]: ...
    def decide(self, context: ClaimContext, claim: OwnershipClaim) -> UUID | None: ...


class ConversationRepository(Protocol):
    def transaction(
        self, conversation_id: UUID
    ) -> AbstractContextManager[ConversationAccess | None]: ...
    def get_access(self, conversation_id: UUID) -> ConversationAccess | None: ...
    def get_view(self, conversation_id: UUID, user_id: UUID) -> ConversationView: ...
    def list_by_user(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> WorkflowPage[ConversationView]: ...
    def list_messages(
        self,
        conversation_id: UUID,
        user_id: UUID,
        *,
        limit: int,
        before: MessageCursor | None,
    ) -> MessagePage: ...
    def send(
        self, conversation_id: UUID, user_id: UUID, body: str, client_message_id: UUID
    ) -> Message: ...
    def mark_read(
        self, conversation_id: UUID, user_id: UUID, last_message_id: UUID | None
    ) -> None: ...
