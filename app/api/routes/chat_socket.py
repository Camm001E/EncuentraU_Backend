import asyncio
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket
from redis.asyncio import Redis
from starlette.concurrency import run_in_threadpool

from app.application.authentication import GetCurrentUser
from app.application.conversations import GetConversation
from app.core.config import Settings, get_settings
from app.infrastructure.auth_security import JWTAccessTokenService
from app.infrastructure.database import session as database_session
from app.infrastructure.database.conversation_repository import (
    SQLAlchemyConversationRepository,
)
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository

router = APIRouter()


def authorize(token, conversation_id, settings):
    with database_session.get_session_factory()() as session:
        user = GetCurrentUser(
            SQLAlchemyUserRepository(session),
            JWTAccessTokenService(settings),
            settings.email_verification_required,
        )(token)
        GetConversation(SQLAlchemyConversationRepository(session))(
            conversation_id, user
        )


@router.websocket("/conversations/{conversation_id}/events")
async def events(
    ws: WebSocket,
    conversation_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
):
    origin = ws.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        await ws.close(code=1008)
        return
    if settings.redis_url is None:
        await ws.close(code=1013)
        return
    await ws.accept()
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=5)
        if len(raw) > 4096:
            raise ValueError()
        # Token travels only inside the encrypted first frame, never in URLs.
        token = raw
        await run_in_threadpool(authorize, token, conversation_id, settings)
        async with Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=2
        ) as client:
            async with client.pubsub() as subscription:
                await subscription.subscribe(f"chat:{conversation_id}")
                await ws.send_json({"type": "ready"})
                while True:
                    event = await subscription.get_message(
                        ignore_subscribe_messages=True, timeout=15
                    )
                    await run_in_threadpool(authorize, token, conversation_id, settings)
                    await ws.send_json({"type": "changed" if event else "heartbeat"})
                    await asyncio.sleep(0.05)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Chat socket closed: %s", type(exc).__name__
        )
        try:
            await ws.close(code=1008)
        except Exception:
            pass
