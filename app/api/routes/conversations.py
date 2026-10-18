from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import get_current_user
from app.api.dependencies.ownership import get_conversation_repository
from app.api.dependencies.privacy import private_response
from app.api.schemas.ownership import (
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    MessageRequest,
    MessageResponse,
    ReadRequest,
)
from app.application.conversations import (
    GetConversation,
    ListConversations,
    ListMessages,
    MarkConversationRead,
    SendMessage,
)
from app.domain.ownership import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.domain.ports.ownership import ConversationRepository
from app.domain.users import User

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    route_class=AuthRoute,
    dependencies=[Depends(private_response)],
)
CurrentUser = Annotated[User, Depends(get_current_user)]
Repository = Annotated[ConversationRepository, Depends(get_conversation_repository)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]


@router.get("/me", response_model=ConversationListResponse)
def list_conversations(
    user: CurrentUser,
    repository: Repository,
    limit: Limit = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return ConversationListResponse.from_page(
        ListConversations(repository)(user, limit=limit, offset=offset)
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: UUID, user: CurrentUser, repository: Repository):
    return ConversationResponse.from_view(
        GetConversation(repository)(conversation_id, user)
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: UUID,
    user: CurrentUser,
    repository: Repository,
    limit: Limit = 50,
    before: Annotated[str | None, Query(max_length=256)] = None,
):
    return MessageListResponse.from_page(
        ListMessages(repository)(conversation_id, user, limit=limit, before=before)
    )


@router.post(
    "/{conversation_id}/messages", response_model=MessageResponse, status_code=201
)
def send_message(
    conversation_id: UUID,
    request: MessageRequest,
    user: CurrentUser,
    repository: Repository,
):
    return MessageResponse.from_message(
        SendMessage(repository)(
            conversation_id, user, request.body, request.client_message_id
        )
    )


@router.post("/{conversation_id}/read", status_code=204)
def mark_read(
    conversation_id: UUID,
    user: CurrentUser,
    repository: Repository,
    request: ReadRequest | None = None,
):
    MarkConversationRead(repository)(
        conversation_id, user, request.last_message_id if request else None
    )
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})
