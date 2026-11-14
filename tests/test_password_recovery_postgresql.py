import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.api.routes.auth import get_email_sender
from app.domain.authentication import InvalidVerificationCodeError
from app.infrastructure.database.models import EmailDeliveryBudget, User
from app.infrastructure.database.password_recovery import PasswordRecovery
from tests.test_authentication import AUTH, bearer
from tests.test_email_verification_postgresql import pg_email as pg_email
from tests.test_password_recovery import NEW_PASSWORD, Mailbox, confirm, request


class Passwords:
    def hash(self, value):
        return "test-new-hash"


def test_concurrent_recovery_resend_and_consumption(pg_email):
    engine, settings, _ = pg_email
    mailbox = Mailbox()

    def send(_):
        with Session(engine) as s:
            PasswordRecovery(s, Passwords(), mailbox, settings).request(
                "test@example.com"
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(send, range(4)))
    assert len(mailbox.messages) == 1
    code = mailbox.messages[0][1]

    def consume(_):
        with Session(engine) as s:
            try:
                PasswordRecovery(s, Passwords(), mailbox, settings).confirm(
                    "test@example.com", code, NEW_PASSWORD
                )
                return True
            except InvalidVerificationCodeError:
                return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(consume, range(4))).count(True) == 1
    with Session(engine) as s:
        u = s.scalar(select(User))
        assert u.session_version == 1 and u.recovery_digest is None
        assert s.get(EmailDeliveryBudget, "global").sent == 1


def test_concurrent_recovery_guesses_stop_after_five(pg_email):
    engine, settings, _ = pg_email
    mailbox = Mailbox()
    with Session(engine) as s:
        PasswordRecovery(s, Passwords(), mailbox, settings).request("test@example.com")
    wrong = "11111111" if mailbox.messages[0][1] != "11111111" else "22222222"

    def guess(_):
        with Session(engine) as s:
            with pytest.raises(InvalidVerificationCodeError):
                PasswordRecovery(s, Passwords(), mailbox, settings).confirm(
                    "test@example.com", wrong, NEW_PASSWORD
                )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(guess, range(8)))
    with Session(engine) as s:
        u = s.scalar(select(User))
        assert u.recovery_attempts == 5 and u.recovery_digest is None
        assert u.session_version == 0


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
def test_password_reset_closes_open_socket_and_preserves_chat(workflow, monkeypatch):
    w = workflow
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Isolated TEST_REDIS_URL required")
    w.settings.redis_url = SecretStr(url)
    monkeypatch.setattr(
        "app.infrastructure.chat_events.get_settings", lambda: w.settings
    )
    mailbox = Mailbox()
    w.client.app.dependency_overrides[get_email_sender] = lambda: mailbox
    _, conversation = w.approved()
    path = f"/api/v1/conversations/{conversation}"
    with w.client.websocket_connect(path + "/events") as ws:
        ws.send_text(w.headers["A"]["Authorization"].removeprefix("Bearer "))
        assert ws.receive_json()["type"] == "ready"
        assert request(w, email="a@example.com").status_code == 200
        assert (
            confirm(w, mailbox.messages[-1][1], email="a@example.com").status_code
            == 200
        )
        r = w.client.post(
            path + "/messages",
            headers=w.headers["B"],
            json={
                "body": "Mensaje después de recuperar el acceso",
                "client_message_id": str(uuid4()),
            },
        )
        assert r.status_code == 201
        with pytest.raises(WebSocketDisconnect):
            for _ in range(3):
                ws.receive_json()
    assert w.client.get(path + "/messages", headers=w.headers["A"]).status_code == 401
    token = w.client.post(
        f"{AUTH}/login", json={"email": "a@example.com", "password": NEW_PASSWORD}
    ).json()["access_token"]
    assert (
        len(w.client.get(path + "/messages", headers=bearer(token)).json()["items"])
        == 1
    )
