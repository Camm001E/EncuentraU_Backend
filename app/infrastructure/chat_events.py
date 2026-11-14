from redis import Redis

from app.core.config import get_settings


def publish_chat_change(conversation_id):
    url = get_settings().redis_url
    if url is None:
        return
    try:
        with Redis.from_url(
            url.get_secret_value(), socket_connect_timeout=1, socket_timeout=1
        ) as client:
            client.publish(f"chat:{conversation_id}", "changed")
    except Exception:
        # PostgreSQL already committed. Clients reconcile through HTTP.
        pass
