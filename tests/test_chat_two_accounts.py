"""Acceptance through the HTTP API with password login and isolated accounts."""

import secrets
from uuid import uuid4

from sqlalchemy.orm import Session

from app.infrastructure.auth_security import get_password_hasher
from app.infrastructure.database.models import User


def test_two_accounts_login_chat_and_reconnect(workflow):
    w = workflow
    passwords = {actor: secrets.token_urlsafe(24) for actor in ("A", "B")}
    with Session(w.engine) as session:
        for actor, password in passwords.items():
            session.get(User, w.ids[actor]).password_hash = get_password_hasher().hash(
                password
            )
        session.commit()

    def login(actor):
        response = w.client.post(
            "/api/v1/auth/login",
            json={
                "email": actor.lower() + "@example.com",
                "password": passwords[actor],
            },
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        token = response.json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        me = w.client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200 and me.json()["id"] == str(w.ids[actor])
        return headers

    for actor in passwords:
        w.headers[actor] = login(actor)
        response = w.client.get("/api/v1/conversations/me", headers=w.headers[actor])
        assert response.status_code == 200 and response.json()["total"] == 0
    claim = w.claim()
    assert claim.status_code == 201
    for actor in passwords:
        assert (
            w.client.get("/api/v1/conversations/me", headers=w.headers[actor]).json()[
                "total"
            ]
            == 0
        )
    approved = w.approve(claim.json()["id"])
    assert approved.status_code == 200
    conversation = approved.json()["conversation_id"]
    path = f"/api/v1/conversations/{conversation}"
    for actor in passwords:
        listed = w.client.get(
            "/api/v1/conversations/me", headers=w.headers[actor]
        ).json()
        assert listed["total"] == 1 and listed["items"][0]["id"] == conversation

    sent = []
    for actor, recipient, text in [
        ("A", "B", "Hola, coordinemos la entrega."),
        ("B", "A", "De acuerdo, en la recepcion."),
    ]:
        payload = {"body": text, "client_message_id": str(uuid4())}
        response = w.client.post(
            path + "/messages", json=payload, headers=w.headers[actor]
        )
        assert response.status_code == 201
        sent.append(response.json()["id"])
        retry = w.client.post(
            path + "/messages", json=payload, headers=w.headers[actor]
        )
        assert retry.json()["id"] == sent[-1]
        detail = w.client.get(path, headers=w.headers[recipient])
        assert detail.json()["unread_count"] == 1
        assert detail.headers["cache-control"] == "private, no-store"
        read = w.client.post(
            path + "/read",
            json={"last_message_id": sent[-1]},
            headers=w.headers[recipient],
        )
        assert read.status_code == 204
        assert (
            w.client.get(path, headers=w.headers[recipient]).json()["unread_count"] == 0
        )

    for actor in passwords:
        headers = login(actor)
        messages = w.client.get(path + "/messages", headers=headers)
        assert messages.status_code == 200
        rows = messages.json()["items"]
        assert [row["id"] for row in rows] == sent
        assert [row["is_mine"] for row in rows] == (
            [True, False] if actor == "A" else [False, True]
        )
    for actor in ("C", "admin"):
        assert (
            w.client.get(path + "/messages", headers=w.headers[actor]).status_code
            == 404
        )
        assert (
            w.client.post(
                path + "/messages",
                headers=w.headers[actor],
                json={"body": "Intrusion", "client_message_id": str(uuid4())},
            ).status_code
            == 404
        )
    assert w.client.get(path + "/messages").status_code == 401


def test_paid_analysis_requires_active_account(workflow):
    from unittest.mock import Mock

    from app.infrastructure.gemini_image_analyzer import get_image_analyzer
    from tests.test_ai_endpoint import FakeImageAnalyzer

    w = workflow
    provider = Mock(wraps=FakeImageAnalyzer())
    w.client.app.dependency_overrides[get_image_analyzer] = lambda: provider
    payload = {"description": "Aud\u00edfonos negros encontrados en la cafeter\u00eda"}
    files = {"image": ("object.jpg", b"fake-image-content", "image/jpeg")}
    assert (
        w.client.post("/api/v1/ai/analyze", data=payload, files=files).status_code
        == 401
    )
    assert (
        w.client.post(
            "/api/v1/ai/analyze",
            data=payload,
            files=files,
            headers=w.headers["inactive"],
        ).status_code
        == 403
    )
    provider.analyze.assert_not_called()
    assert (
        w.client.post(
            "/api/v1/ai/analyze", data=payload, files=files, headers=w.headers["A"]
        ).status_code
        == 200
    )
    provider.analyze.assert_called_once()
