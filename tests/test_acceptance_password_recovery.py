"""Two fresh accounts, simulated mailbox, real PostgreSQL/Redis and HTTP/WS routes."""

import os
import time
from datetime import date
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_email_sender
from app.infrastructure.database.models import User
from tests.test_authentication import AUTH, bearer
from tests.test_password_recovery import NEW_PASSWORD, Mailbox


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
def test_verified_two_account_recovery_chat_and_delivery(workflow, monkeypatch):
    w = workflow
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("Isolated PostgreSQL and Redis required")
    w.settings.email_verification_required = True
    w.settings.redis_url = SecretStr(redis_url)
    monkeypatch.setattr(
        "app.infrastructure.chat_events.get_settings", lambda: w.settings
    )
    mailbox = Mailbox()
    w.client.app.dependency_overrides[get_email_sender] = lambda: mailbox
    with Session(w.engine) as s:
        s.get(User, w.ids["admin"]).email_verified = True
        s.commit()
    accounts, headers, reports = {}, {}, {}

    def call(method, path, actor=None, expected=200, **kwargs):
        auth_headers = (
            w.headers["admin"] if actor == "admin" else headers.get(actor, {})
        )
        response = w.client.request(method, path, headers=auth_headers, **kwargs)
        assert response.status_code == expected, response.text
        return response.json() if response.content else None

    for actor in ("A", "B"):
        credentials = {
            "email": uuid4().hex + "@example.com",
            "password": "Test-password-123",
        }
        accounts[actor] = credentials
        created = call(
            "POST",
            f"{AUTH}/register",
            expected=201,
            json={
                **credentials,
                "full_name": "Aceptación " + actor,
                "student_code": uuid4().hex,
            },
        )
        assert not created["email_verified"]
        call("POST", f"{AUTH}/login", expected=403, json=credentials)
        if actor == "B":
            time.sleep(2.05)  # Exercise the real shared mail spacing rule.
        call("POST", f"{AUTH}/verification/request", json=credentials)
        call(
            "POST",
            f"{AUTH}/verification/confirm",
            json={**credentials, "code": mailbox.messages[-1][1]},
        )
        logged = call("POST", f"{AUTH}/login", json=credentials)
        assert logged["user"]["id"] == created["id"]
        headers[actor] = bearer(logged["access_token"])
        report = call(
            "POST",
            "/api/v1/reports",
            actor,
            201,
            json={
                "report_type": "lost" if actor == "A" else "found",
                "object_type": "audífonos de diadema",
                "category": "electronica",
                "primary_color": "negro",
                "secondary_colors": ["azul"],
                "shape": "diadema acolchada",
                "description": (
                    "Caso de aceptación: audífonos negros con detalles azules."
                ),
                "location": "Cafetería central",
                "event_date": str(date.today()),
                "private_feature": "Detalle reservado para revisión del administrador.",
            },
        )
        reports[actor] = report["id"]
        photo = BytesIO()
        Image.new("RGB", (240, 240), (20, 30, 40 if actor == "A" else 50)).save(
            photo, "JPEG"
        )
        call(
            "PUT",
            f"/api/v1/reports/{report['id']}/image",
            actor,
            files={"image": ("objeto.jpg", photo.getvalue(), "image/jpeg")},
        )
        assert (
            w.client.get(
                f"/api/v1/reports/{report['id']}/image/content", headers=headers[actor]
            ).status_code
            == 200
        )
        assert (
            w.client.get(f"/api/v1/reports/{report['id']}/image/content").status_code
            == 401
        )

    pairs = call("POST", f"/api/v1/reports/{reports['A']}/matches/generate", "A")
    pair = next(
        item
        for item in pairs["items"]
        if item["candidate_report"]["id"] == reports["B"]
    )
    claim = call(
        "POST",
        f"/api/v1/matches/{pair['id']}/claims",
        "A",
        201,
        json={
            "ownership_evidence": (
                "Detalle reservado conocido por el propietario "
                "en la prueba de aceptación."
            )
        },
    )
    call("POST", f"/api/v1/admin/claims/{claim['id']}/approve", "B", 403)
    approval = call("POST", f"/api/v1/admin/claims/{claim['id']}/approve", "admin")
    chat = f"/api/v1/conversations/{approval['conversation_id']}"
    with (
        w.client.websocket_connect(chat + "/events") as a,
        w.client.websocket_connect(chat + "/events") as b,
    ):
        for ws, actor in ((a, "A"), (b, "B")):
            ws.send_text(headers[actor]["Authorization"].removeprefix("Bearer "))
            assert ws.receive_json()["type"] == "ready"
        for actor in ("A", "B"):
            call(
                "POST",
                chat + "/messages",
                actor,
                201,
                json={
                    "body": "Mensaje privado de " + actor,
                    "client_message_id": str(uuid4()),
                },
            )
            for ws in (a, b):
                for _ in range(5):
                    if ws.receive_json()["type"] == "changed":
                        break
                else:
                    pytest.fail("Missing Redis notification")
    call("GET", chat + "/messages", "admin", 404)
    call("GET", chat + "/messages", expected=401)
    time.sleep(2.05)
    call("POST", f"{AUTH}/password/request", json={"email": accounts["A"]["email"]})
    call(
        "POST",
        f"{AUTH}/password/confirm",
        json={
            "email": accounts["A"]["email"],
            "code": mailbox.messages[-1][1],
            "new_password": NEW_PASSWORD,
        },
    )
    call("GET", chat + "/messages", "A", 401)
    call("POST", f"{AUTH}/login", expected=401, json=accounts["A"])
    accounts["A"]["password"] = NEW_PASSWORD
    for actor in ("A", "B"):
        logged = call("POST", f"{AUTH}/login", json=accounts[actor])
        headers[actor] = bearer(logged["access_token"])
        assert len(call("GET", chat + "/messages", actor)["items"]) == 2
    delivery = call("GET", chat + "/delivery", "A")
    for actor in ("A", "B"):
        call("POST", f"/api/v1/deliveries/{delivery['id']}/confirm", actor)
    closed = call(
        "POST",
        f"/api/v1/admin/deliveries/{delivery['id']}/complete",
        "admin",
        json={"admin_note": "Cierre de aceptación con recuperación de acceso."},
    )
    assert closed["status"] == "completed"
    for actor in ("A", "B"):
        assert call("GET", chat + "/delivery", actor)["status"] == "completed"
        assert (
            call("GET", f"/api/v1/reports/{reports[actor]}", actor)["status"]
            == "resolved"
        )
    assert call("GET", f"/api/v1/deliveries/{delivery['id']}/events", "A")
    with Session(w.engine) as s:
        recovered = s.scalar(select(User).where(User.email == accounts["A"]["email"]))
        assert recovered.session_version == 1 and recovered.email_verified
