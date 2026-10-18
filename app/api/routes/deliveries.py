from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.auth_errors import AuthRoute
from app.api.dependencies.authentication import get_current_user
from app.api.dependencies.deliveries import get_delivery_repository
from app.api.dependencies.ownership import get_admin
from app.api.dependencies.privacy import private_response
from app.api.schemas.deliveries import (
    AdminDeliveryListResponse,
    AdminDeliveryResponse,
    DeliveryEventResponse,
    DeliveryListResponse,
    DeliveryNoteRequest,
    DeliveryResponse,
    DeliverySummaryResponse,
    DisputeRequest,
    ReopenRequest,
    event_views,
)
from app.api.schemas.ownership import PrivateInput
from app.application.deliveries import (
    CompleteDelivery,
    ConfirmDelivery,
    GetAdminDelivery,
    GetDelivery,
    ListAdminDeliveries,
    ListDeliveryEvents,
    ListMyDeliveries,
    OpenDeliveryDispute,
    ReopenDelivery,
)
from app.domain.deliveries import DeliveryStatus
from app.domain.ports.deliveries import DeliveryRepository
from app.domain.users import User, UserRole

router = APIRouter(
    tags=["deliveries"], route_class=AuthRoute, dependencies=[Depends(private_response)]
)
CurrentUser = Annotated[User, Depends(get_current_user)]
Admin = Annotated[User, Depends(get_admin)]
Repository = Annotated[DeliveryRepository, Depends(get_delivery_repository)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/deliveries/me", response_model=DeliveryListResponse)
def list_my_deliveries(
    user: CurrentUser,
    repository: Repository,
    status: DeliveryStatus | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
):
    page = ListMyDeliveries(repository)(user, status=status, limit=limit, offset=offset)
    return DeliveryListResponse(
        items=[DeliveryResponse.from_context(c, user) for c in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/conversations/{conversation_id}/delivery", response_model=DeliveryResponse
)
def get_delivery(conversation_id: UUID, user: CurrentUser, repository: Repository):
    return DeliveryResponse.from_context(
        GetDelivery(repository)(user, conversation_id=conversation_id), user
    )


@router.post("/deliveries/{delivery_id}/confirm", response_model=DeliveryResponse)
def confirm_delivery(
    delivery_id: UUID,
    user: CurrentUser,
    repository: Repository,
    request: PrivateInput | None = None,
):
    return DeliveryResponse.from_context(
        ConfirmDelivery(repository)(delivery_id, user), user
    )


@router.post("/deliveries/{delivery_id}/dispute", response_model=DeliveryResponse)
def dispute_delivery(
    delivery_id: UUID,
    request: DisputeRequest,
    user: CurrentUser,
    repository: Repository,
):
    return DeliveryResponse.from_context(
        OpenDeliveryDispute(repository)(delivery_id, user, request.reason), user
    )


@router.get(
    "/deliveries/{delivery_id}/events", response_model=list[DeliveryEventResponse]
)
def list_delivery_events(delivery_id: UUID, user: CurrentUser, repository: Repository):
    context = ListDeliveryEvents(repository)(delivery_id, user)
    return event_views(context, admin=user.role == UserRole.ADMIN)


@router.get("/admin/deliveries", response_model=AdminDeliveryListResponse)
def list_admin_deliveries(
    user: Admin,
    repository: Repository,
    status: DeliveryStatus | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
):
    page = ListAdminDeliveries(repository)(
        user, status=status, limit=limit, offset=offset
    )
    return AdminDeliveryListResponse(
        items=[
            DeliverySummaryResponse(**DeliverySummaryResponse.values(c))
            for c in page.items
        ],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/deliveries/{delivery_id}", response_model=AdminDeliveryResponse)
def get_admin_delivery(delivery_id: UUID, user: Admin, repository: Repository):
    return AdminDeliveryResponse.from_context(
        GetAdminDelivery(repository)(delivery_id, user)
    )


@router.post(
    "/admin/deliveries/{delivery_id}/complete", response_model=AdminDeliveryResponse
)
def complete_delivery(
    delivery_id: UUID,
    user: Admin,
    repository: Repository,
    request: DeliveryNoteRequest | None = None,
):
    return AdminDeliveryResponse.from_context(
        CompleteDelivery(repository)(
            delivery_id, user, request.admin_note if request else None
        )
    )


@router.post(
    "/admin/deliveries/{delivery_id}/reopen", response_model=AdminDeliveryResponse
)
def reopen_delivery(
    delivery_id: UUID, request: ReopenRequest, user: Admin, repository: Repository
):
    return AdminDeliveryResponse.from_context(
        ReopenDelivery(repository)(delivery_id, user, request.admin_note)
    )
