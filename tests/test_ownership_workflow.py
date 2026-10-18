import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.application.ownership_claims import ApproveClaim, SubmitOwnershipClaim
from app.cli.create_admin import main as create_admin
from app.domain.ownership import (
    MessageCursor,
    WorkflowConflict,
    WorkflowValidation,
    display_name,
    normalize_text,
)
from app.infrastructure.auth_security import get_password_hasher
from app.infrastructure.database.models import (
    Conversation,
    ConversationParticipant,
    ObjectMatch,
    ObjectReport,
    OwnershipClaim,
    User,
)
from app.infrastructure.database.ownership_repository import (
    SQLAlchemyOwnershipClaimRepository,
)
from app.infrastructure.database.user_repository import SQLAlchemyUserRepository


def assert_private(data, *, admin=False, owner=False):
    forbidden = {
        "user_id",
        "claimant_user_id",
        "custodian_user_id",
        "admin_id",
        "email",
        "student_code",
        "password",
        "password_hash",
        "access_token",
        "storage_key",
        "extracted_data",
        "sender_id",
        "original_filename",
    }
    if not admin:
        forbidden |= {
            "private_feature",
            "lost_private_feature",
            "found_private_feature",
            "admin_note",
        }
    if not owner and not admin:
        forbidden.add("ownership_evidence")

    def visit(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)


def test_claim_and_asymmetric_privacy(workflow):
    w = workflow
    response = w.claim()
    assert response.status_code == 201
    claim = response.json()
    assert claim["relationship"] == "claimant" and claim["status"] == "pending"
    assert_private(claim, owner=True)
    assert response.headers["cache-control"] == "private, no-store"
    identifier = claim["id"]
    for path in (f"/claims/{identifier}", f"/matches/{w.match_id}/claim"):
        mine = w.client.get("/api/v1" + path, headers=w.headers["A"])
        assert mine.status_code == 200 and mine.json()["ownership_evidence"]
        other = w.client.get("/api/v1" + path, headers=w.headers["B"])
        assert other.status_code == 200 and other.json()["relationship"] == "custodian"
        assert_private(other.json())
        assert w.client.get("/api/v1" + path, headers=w.headers["C"]).status_code == 404
    for actor in ("A", "B", "C"):
        listed = w.client.get(
            "/api/v1/claims/me?status=pending&limit=1", headers=w.headers[actor]
        )
        assert listed.status_code == 200 and listed.json()["total"] == (
            0 if actor == "C" else 1
        )
        assert_private(listed.json(), owner=actor == "A")


@pytest.mark.parametrize("actor", ["B", "C", "admin"])
def test_only_lost_owner_can_claim(workflow, actor):
    assert workflow.claim(actor=actor).status_code == 404


@pytest.mark.parametrize(
    "status,report",
    [("cancelled", "lost"), ("resolved", "found"), ("cancelled", "found")],
)
def test_inactive_reports_block_claim(workflow, status, report):
    with Session(workflow.engine) as session:
        row = session.get(
            ObjectReport, workflow.lost_id if report == "lost" else workflow.found_id
        )
        row.status = status
        session.commit()
    assert workflow.claim().status_code == 409


@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_final_matches_cannot_be_claimed(workflow, status):
    with Session(workflow.engine) as session:
        session.get(ObjectMatch, workflow.match_id).status = status
        session.commit()
    assert workflow.claim().status_code == 409


def test_same_owner_is_blocked(workflow):
    with Session(workflow.engine) as session:
        session.get(ObjectReport, workflow.found_id).user_id = workflow.ids["A"]
        session.commit()
    assert workflow.claim().status_code == 409


@pytest.mark.parametrize("evidence", ["", "    ", "corta", "x" * 4001, "\u200b" * 20])
def test_evidence_validation(workflow, evidence):
    response = workflow.claim(evidence)
    assert response.status_code == 422
    assert "input" not in str(response.json())


def test_claim_retries_do_not_overwrite_evidence(workflow):
    a, b = workflow.claim(), workflow.claim()
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert (
        workflow.claim("Una respuesta diferente y suficientemente larga").status_code
        == 409
    )
    with Session(workflow.engine) as session:
        assert session.scalar(select(func.count()).select_from(OwnershipClaim)) == 1


def test_admin_queue_and_detail_are_allowlisted(workflow):
    claim = workflow.claim().json()
    listed = workflow.client.get(
        "/api/v1/admin/claims?status=pending&limit=1", headers=workflow.headers["admin"]
    )
    assert listed.status_code == 200 and listed.json()["total"] == 1
    detail = workflow.client.get(
        "/api/v1/admin/claims/" + claim["id"], headers=workflow.headers["admin"]
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["lost_private_feature"] == "Detalle privado perdido"
    assert body["found_private_feature"] == "Detalle privado encontrado"
    assert len(body["match"]["factors"]) == 9
    assert body["ownership_evidence"] == claim["ownership_evidence"]
    assert_private(body, admin=True)
    assert (
        workflow.client.get(
            "/api/v1/admin/claims?limit=101", headers=workflow.headers["admin"]
        ).status_code
        == 422
    )
    assert (
        workflow.client.get(
            "/api/v1/admin/claims?offset=1", headers=workflow.headers["admin"]
        ).json()["items"]
        == []
    )


@pytest.mark.parametrize("actor", ["A", "B", "C", "inactive"])
def test_admin_rbac_and_inactive_admin(workflow, actor):
    identifier = workflow.claim().json()["id"]
    for method, path, body in [
        ("GET", "/admin/claims", None),
        ("GET", f"/admin/claims/{identifier}", None),
        ("POST", f"/admin/claims/{identifier}/approve", {}),
        (
            "POST",
            f"/admin/claims/{identifier}/reject",
            {"rejection_reason": "No coincide"},
        ),
    ]:
        response = workflow.client.request(
            method, "/api/v1" + path, json=body, headers=workflow.headers[actor]
        )
        assert response.status_code == 403


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_jwt_is_required(workflow, headers):
    for method, path, body in [
        ("GET", "/claims/me", None),
        ("GET", "/conversations/me", None),
        (
            "POST",
            f"/matches/{workflow.match_id}/claims",
            {"ownership_evidence": "Descripción privada adecuada"},
        ),
    ]:
        response = workflow.client.request(
            method, "/api/v1" + path, json=body, headers=headers
        )
        assert response.status_code == 401


def test_approval_is_atomic_and_creates_two_participants(workflow):
    claim, conversation = workflow.approved()
    for actor in ("A", "B"):
        view = workflow.client.get(
            f"/api/v1/claims/{claim}", headers=workflow.headers[actor]
        ).json()
        assert view["status"] == "approved" and view["conversation_id"] == conversation
        assert view["match"]["status"] == "accepted"
        assert_private(view, owner=actor == "A")
    with Session(workflow.engine) as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 1
        participants = set(session.scalars(select(ConversationParticipant.user_id)))
        assert participants == {workflow.ids["A"], workflow.ids["B"]}
    assert workflow.approve(claim).status_code == 409
    rejected = workflow.client.post(
        f"/api/v1/admin/claims/{claim}/reject",
        json={"rejection_reason": "Una decisión final diferente"},
        headers=workflow.headers["admin"],
    )
    assert rejected.status_code == 409
    assert workflow.claim().status_code == 409


def test_failed_conversation_creation_rolls_back_everything(workflow, monkeypatch):
    claim = workflow.claim().json()["id"]
    original = SQLAlchemyOwnershipClaimRepository.decide

    def failure(self, *args):
        original(self, *args)
        raise SQLAlchemyError("Test failure: no transaction may escape")

    monkeypatch.setattr(SQLAlchemyOwnershipClaimRepository, "decide", failure)
    assert workflow.approve(claim).status_code == 503
    with Session(workflow.engine) as session:
        assert session.get(OwnershipClaim, UUID(claim)).status == "pending"
        assert session.get(ObjectMatch, workflow.match_id).status == "pending"
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert (
            session.scalar(select(func.count()).select_from(ConversationParticipant))
            == 0
        )


def test_rejection_requires_reason_and_never_creates_chat(workflow):
    claim = workflow.claim().json()["id"]
    path = f"/api/v1/admin/claims/{claim}/reject"
    for body in ({}, {"rejection_reason": "  "}):
        assert (
            workflow.client.post(
                path, json=body, headers=workflow.headers["admin"]
            ).status_code
            == 422
        )
    response = workflow.client.post(
        path,
        json={
            "rejection_reason": "La característica no coincide.",
            "admin_note": "Nota interna que no debe ver el estudiante",
        },
        headers=workflow.headers["admin"],
    )
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert response.json()["conversation_id"] is None
    for actor in ("A", "B"):
        body = workflow.client.get(
            f"/api/v1/claims/{claim}", headers=workflow.headers[actor]
        ).json()
        assert body["rejection_reason"] == "La característica no coincide."
        assert body["match"]["status"] == "rejected"
        assert_private(body, owner=actor == "A")
        assert (
            workflow.client.get(
                "/api/v1/conversations/me", headers=workflow.headers[actor]
            ).json()["total"]
            == 0
        )
    with Session(workflow.engine) as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0


def test_chat_is_blocked_before_approval(workflow):
    workflow.claim()
    identifier = uuid4()
    for actor in ("A", "B", "C", "admin"):
        assert (
            workflow.client.get(
                f"/api/v1/conversations/{identifier}", headers=workflow.headers[actor]
            ).status_code
            == 404
        )
        assert (
            workflow.client.get(
                "/api/v1/conversations/me", headers=workflow.headers[actor]
            ).json()["total"]
            == 0
        )


@pytest.mark.parametrize("actor", ["C", "admin"])
def test_chat_is_private_even_for_admin(workflow, actor):
    _, conversation = workflow.approved()
    for method, path, body in [
        ("GET", "", None),
        ("GET", "/messages", None),
        (
            "POST",
            "/messages",
            {"body": "Mensaje de prueba", "client_message_id": str(uuid4())},
        ),
        ("POST", "/read", {}),
    ]:
        assert (
            workflow.client.request(
                method,
                f"/api/v1/conversations/{conversation}" + path,
                json=body,
                headers=workflow.headers[actor],
            ).status_code
            == 404
        )


def send(workflow, conversation, body="Mensaje de prueba", actor="A", client_id=None):
    return workflow.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"body": body, "client_message_id": str(client_id or uuid4())},
        headers=workflow.headers[actor],
    )


def test_messages_idempotency_order_pagination_read_and_privacy(workflow):
    _, conversation = workflow.approved()
    ids = []
    for i in range(5):
        response = send(workflow, conversation, body=f"Mensaje de prueba {i}")
        assert response.status_code == 201
        ids.append(response.json()["id"])
    client_id = uuid4()
    first = send(
        workflow,
        conversation,
        " Texto con espacios \r\n normalizados ",
        client_id=client_id,
    )
    again = send(
        workflow, conversation, "Texto con espacios\nnormalizados", client_id=client_id
    )
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert (
        send(
            workflow, conversation, "Un contenido diferente", client_id=client_id
        ).status_code
        == 409
    )
    path = f"/api/v1/conversations/{conversation}"
    view = workflow.client.get(path, headers=workflow.headers["B"]).json()
    assert view["unread_count"] == 6 and view["other_display_name"] == "Alice"
    assert_private(view)
    cursor, received = None, []
    while True:
        params = {"limit": 2}
        if cursor:
            params["before"] = cursor
        response = workflow.client.get(
            path + "/messages", params=params, headers=workflow.headers["B"]
        )
        assert response.status_code == 200
        page = response.json()
        assert all(not row["is_mine"] for row in page["items"])
        assert all(row["created_at"].endswith(("Z", "+00:00")) for row in page["items"])
        received = [r["id"] for r in page["items"]] + received
        assert_private(page)
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert received == ids + [first.json()["id"]]
    assert (
        workflow.client.post(
            path + "/read",
            json={"last_message_id": first.json()["id"]},
            headers=workflow.headers["B"],
        ).status_code
        == 204
    )
    assert (
        workflow.client.get(path, headers=workflow.headers["B"]).json()["unread_count"]
        == 0
    )
    reply = send(workflow, conversation, actor="B")
    assert reply.status_code == 201
    assert (
        workflow.client.get(path, headers=workflow.headers["A"]).json()["unread_count"]
        == 1
    )
    assert (
        workflow.client.post(path + "/read", headers=workflow.headers["A"]).status_code
        == 204
    )
    listed = workflow.client.get(
        "/api/v1/conversations/me", headers=workflow.headers["A"]
    ).json()
    assert listed["total"] == 1 and listed["items"][0]["unread_count"] == 0
    assert_private(listed)


@pytest.mark.parametrize("body", ["", " \n\t ", "x" * 2001, "\u0000\u200b"])
def test_message_limits(workflow, body):
    _, conversation = workflow.approved()
    assert send(workflow, conversation, body).status_code == 422


def test_invalid_cursor_read_ids_and_immutable_messages(workflow):
    _, conversation = workflow.approved()
    path = f"/api/v1/conversations/{conversation}"
    assert (
        workflow.client.get(
            path + "/messages?before=invalid", headers=workflow.headers["A"]
        ).status_code
        == 422
    )
    assert (
        workflow.client.get(
            path + "/messages?limit=101", headers=workflow.headers["A"]
        ).status_code
        == 422
    )
    assert (
        workflow.client.post(
            path + "/read",
            json={"last_message_id": str(uuid4())},
            headers=workflow.headers["A"],
        ).status_code
        == 404
    )
    message = send(workflow, conversation).json()["id"]
    for method in ("PATCH", "DELETE"):
        assert workflow.client.request(
            method, path + "/messages/" + message, headers=workflow.headers["A"]
        ).status_code in (404, 405)


def test_admin_can_read_images_but_not_modify_others(workflow):
    image = Image.new("RGB", (32, 32), "green")
    data = BytesIO()
    image.save(data, format="PNG")
    path = f"/api/v1/reports/{workflow.lost_id}/image"
    assert (
        workflow.client.put(
            path,
            files={"image": ("photo.png", data.getvalue(), "image/png")},
            headers=workflow.headers["A"],
        ).status_code
        == 200
    )
    for suffix in ("", "/content"):
        admin = workflow.client.get(path + suffix, headers=workflow.headers["admin"])
        assert (
            admin.status_code == 200
            and admin.headers["cache-control"] == "private, no-store"
        )
        assert (
            workflow.client.get(
                path + suffix, headers=workflow.headers["C"]
            ).status_code
            == 404
        )
        assert (
            workflow.client.get(
                path + suffix, headers=workflow.headers["inactive"]
            ).status_code
            == 403
        )
    assert (
        workflow.client.delete(path, headers=workflow.headers["admin"]).status_code
        == 404
    )


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
def test_concurrent_approval_has_exactly_one_conversation(workflow):
    claim_id = UUID(workflow.claim().json()["id"])

    def approve(_):
        with Session(workflow.engine, expire_on_commit=False) as session:
            admin = SQLAlchemyUserRepository(session).get_by_id(workflow.ids["admin"])
            try:
                ApproveClaim(SQLAlchemyOwnershipClaimRepository(session))(
                    claim_id, admin
                )
                return 200
            except WorkflowConflict:
                return 409

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, range(2))) == [200, 409]
    with Session(workflow.engine) as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 1
        assert (
            session.scalar(select(func.count()).select_from(ConversationParticipant))
            == 2
        )


@pytest.mark.parametrize("workflow", ["postgresql"], indirect=True)
def test_concurrent_submission_is_idempotent(workflow):
    def submit(_):
        with Session(workflow.engine, expire_on_commit=False) as session:
            user = SQLAlchemyUserRepository(session).get_by_id(workflow.ids["A"])
            return SubmitOwnershipClaim(SQLAlchemyOwnershipClaimRepository(session))(
                workflow.match_id, user, "Una característica privada de prueba"
            ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(submit, range(2)))
    assert result[0] == result[1]


def test_cli_admin_uses_argon2_and_never_prints_credentials(workflow, capsys):
    password = secrets.token_urlsafe(32)
    responses = iter(["Administración de prueba", "cli.admin@example.com", "CLI-ADMIN"])
    factory = sessionmaker(workflow.engine, expire_on_commit=False)
    result = create_admin(
        input_fn=lambda _: next(responses),
        password_fn=lambda _: password,
        session_factory=factory,
    )
    assert result == 0
    assert password not in capsys.readouterr().out
    with Session(workflow.engine) as session:
        admin = session.scalar(select(User).where(User.student_code == "CLI-ADMIN"))
        assert admin.role == "admin" and admin.is_active
        assert get_password_hasher().verify(password, admin.password_hash)
    responses = iter(["Otro nombre", "cli.admin@example.com", "CLI-OTHER"])
    assert (
        create_admin(
            input_fn=lambda _: next(responses),
            password_fn=lambda _: password,
            session_factory=factory,
        )
        == 1
    )


def test_pure_normalization_cursor_and_display_names():
    assert normalize_text("  Hola\r\n  mundo\t \u200b") == "Hola\nmundo"
    assert display_name("Nombre Apellido") == "Nombre"
    assert display_name("correo@example.com") == "Estudiante"
    cursor = MessageCursor(datetime.now(UTC), uuid4())
    assert MessageCursor.decode(cursor.encode()) == cursor
    for value in ("invalid", "x" * 257, "e30"):
        with pytest.raises(WorkflowValidation):
            MessageCursor.decode(value)
