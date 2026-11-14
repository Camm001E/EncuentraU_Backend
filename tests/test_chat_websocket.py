import os
from uuid import uuid4

import pytest
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
def test_redis_socket_participants_and_privacy(workflow, monkeypatch):
    w = workflow
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Isolated TEST_REDIS_URL required")
    w.settings.redis_url = SecretStr(url)
    monkeypatch.setattr(
        "app.infrastructure.chat_events.get_settings", lambda: w.settings
    )
    _, conversation = w.approved()
    path = f"/api/v1/conversations/{conversation}/events"
    with w.client.websocket_connect(path) as a, w.client.websocket_connect(path) as b:
        a.send_text(w.headers["A"]["Authorization"].removeprefix("Bearer "))
        b.send_text(w.headers["B"]["Authorization"].removeprefix("Bearer "))
        assert a.receive_json()["type"] == "ready"
        assert b.receive_json()["type"] == "ready"
        response = w.client.post(
            f"/api/v1/conversations/{conversation}/messages",
            headers=w.headers["A"],
            json={"body": "Mensaje real por HTTP", "client_message_id": str(uuid4())},
        )
        assert response.status_code == 201
        for ws in (a, b):
            for _ in range(3):
                if ws.receive_json()["type"] == "changed":
                    break
            else:
                pytest.fail("No Redis event")
    for actor in ("C", "admin", "inactive"):
        with w.client.websocket_connect(path) as ws:
            ws.send_text(w.headers[actor]["Authorization"].removeprefix("Bearer "))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with w.client.websocket_connect(
            path, headers={"origin": "https://untrusted.example"}
        ):
            pass
