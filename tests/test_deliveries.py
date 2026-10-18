from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    Conversation,
    Delivery,
    DeliveryEvent,
    Message,
    ObjectMatch,
    ObjectReport,
    OwnershipClaim,
)


def call(w, method, path, actor="A", **kwargs):
    return getattr(w.client, method)(
        "/api/v1/" + path, headers=w.headers[actor], **kwargs
    )


def approved(w):
    claim, conversation = w.approved()
    response = call(w, "get", f"conversations/{conversation}/delivery")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    return response.json(), claim, conversation


def confirm(w, delivery, actor="A"):
    return call(w, "post", f"deliveries/{delivery['id']}/confirm", actor)


def complete(w, delivery, **kwargs):
    return call(
        w, "post", f"admin/deliveries/{delivery['id']}/complete", "admin", **kwargs
    )


def test_delivery_created_atomically_with_approval(workflow):
    d, claim, conversation = approved(workflow)
    assert d["claim_id"] == claim and d["conversation_id"] == conversation
    assert d["status"] == "coordinating" and d["can_confirm"]
    assert d["relationship"] == "claimant"
    assert [e["event_type"] for e in d["events"]] == ["delivery_created"]
    with Session(workflow.engine) as s:
        assert s.scalar(select(func.count()).select_from(Delivery)) == 1
        assert s.scalar(select(func.count()).select_from(DeliveryEvent)) == 1


@pytest.mark.parametrize("order", [("A", "B"), ("B", "A")])
def test_confirmations_idempotent_and_atomic_closure(workflow, order):
    d, claim, conversation = approved(workflow)
    sent = call(
        workflow,
        "post",
        f"conversations/{conversation}/messages",
        json={"body": "Coordinamos el intercambio", "client_message_id": str(uuid4())},
    )
    assert sent.status_code == 201
    assert confirm(workflow, d, order[0]).json()["status"] == "awaiting_confirmations"
    first = confirm(workflow, d, order[0]).json()
    assert len(first["events"]) == 2
    second = confirm(workflow, d, order[1]).json()
    assert second["status"] == "awaiting_admin"
    assert not second["can_confirm"] and second["can_dispute"]
    result = complete(workflow, d, json={"admin_note": "Nota solo administrativa"})
    assert result.status_code == 200 and result.json()["status"] == "completed"
    student = call(workflow, "get", f"conversations/{conversation}/delivery").json()
    assert student["status"] == "completed" and not student["can_dispute"]
    assert student["events"][-1]["note"] is None
    assert "Nota solo administrativa" not in str(student)
    assert confirm(workflow, d).status_code == 409
    assert complete(workflow, d).status_code == 409
    assert call(workflow, "get", f"conversations/{conversation}").status_code == 200
    assert (
        call(workflow, "get", f"conversations/{conversation}/messages").json()["items"][
            0
        ]["id"]
        == sent.json()["id"]
    )
    assert (
        call(workflow, "post", f"conversations/{conversation}/read").status_code == 204
    )
    assert (
        call(
            workflow,
            "post",
            f"conversations/{conversation}/messages",
            json={"body": "Nuevo", "client_message_id": str(uuid4())},
        ).status_code
        == 409
    )
    assert (
        call(workflow, "get", "conversations/me").json()["items"][0]["status"]
        == "closed"
    )
    with Session(workflow.engine) as s:
        assert s.get(ObjectReport, workflow.lost_id).status == "resolved"
        assert s.get(ObjectReport, workflow.found_id).status == "resolved"
        assert s.get(ObjectMatch, workflow.match_id).status == "accepted"
        assert s.get(OwnershipClaim, UUID(claim)).status == "approved"
        assert s.get(Conversation, UUID(conversation)).status == "closed"
        assert s.scalar(select(func.count()).select_from(Message)) == 1


@pytest.mark.parametrize("actor", ["A", "B"])
@pytest.mark.parametrize("stage", [0, 1, 2])
def test_dispute_reopen_retains_history_and_resets_current_confirmation(
    workflow, actor, stage
):
    d, _, conversation = approved(workflow)
    for participant in ("A", "B")[:stage]:
        assert confirm(workflow, d, participant).status_code == 200
    reason = "El objeto entregado no corresponde al reportado."
    dispute = call(
        workflow,
        "post",
        f"deliveries/{d['id']}/dispute",
        actor,
        json={"reason": reason},
    )
    assert dispute.status_code == 200 and dispute.json()["status"] == "disputed"
    assert confirm(workflow, d).status_code == 409
    assert complete(workflow, d).status_code == 409
    assert (
        call(
            workflow,
            "post",
            f"deliveries/{d['id']}/dispute",
            actor,
            json={"reason": reason},
        ).status_code
        == 409
    )
    assert (
        call(
            workflow,
            "post",
            f"conversations/{conversation}/messages",
            json={"body": "Revisemos el problema", "client_message_id": str(uuid4())},
        ).status_code
        == 201
    )
    reopened = call(
        workflow,
        "post",
        f"admin/deliveries/{d['id']}/reopen",
        "admin",
        json={"admin_note": "Nueva coordinación necesaria"},
    )
    assert reopened.status_code == 200
    data = reopened.json()
    assert data["status"] == "coordinating" and data["dispute_reason"] is None
    assert (
        data["claimant_confirmed_at"] is None and data["custodian_confirmed_at"] is None
    )
    assert any(e["note"] == reason for e in data["events"])
    assert len(data["events"]) == stage + 3
    assert confirm(workflow, d).status_code == 200
    assert confirm(workflow, d, "B").json()["status"] == "awaiting_admin"
    assert complete(workflow, d).status_code == 200


def test_reopen_awaiting_admin_is_explicit_administrative_exception(workflow):
    d, _, _ = approved(workflow)
    assert confirm(workflow, d).status_code == 200
    assert confirm(workflow, d, "B").status_code == 200
    assert (
        call(
            workflow,
            "post",
            f"admin/deliveries/{d['id']}/reopen",
            "admin",
            json={"admin_note": "Revisar nuevamente"},
        ).json()["status"]
        == "coordinating"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "deliveries/me"),
        ("get", "conversations/{conversation}/delivery"),
        ("get", "deliveries/{delivery}/events"),
        ("post", "deliveries/{delivery}/confirm"),
    ],
)
def test_protected_participant_endpoints(workflow, method, path):
    d, _, conv = approved(workflow)
    path = path.format(conversation=conv, delivery=d["id"])
    assert getattr(workflow.client, method)("/api/v1/" + path).status_code == 401
    assert call(workflow, method, path, "inactive").status_code == 403
    if path != "deliveries/me":
        assert call(workflow, method, path, "C").status_code == 404
        assert call(workflow, method, path, "B").status_code == 200
    else:
        assert call(workflow, method, path, "C").json()["total"] == 0


@pytest.mark.parametrize("action", ["complete", "reopen"])
def test_admin_rbac_and_invalid_transitions(workflow, action):
    d, _, _ = approved(workflow)
    path = f"admin/deliveries/{d['id']}/{action}"
    assert (
        call(
            workflow, "post", path, json={"admin_note": "Revisión necesaria"}
        ).status_code
        == 403
    )
    assert (
        call(
            workflow,
            "post",
            path,
            "inactive",
            json={"admin_note": "Revisión necesaria"},
        ).status_code
        == 403
    )
    assert (
        call(
            workflow, "post", path, "admin", json={"admin_note": "Revisión necesaria"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("reason", ["", "corto", "x" * 2001, " " * 20])
def test_dispute_validation(workflow, reason):
    d, _, _ = approved(workflow)
    assert (
        call(
            workflow, "post", f"deliveries/{d['id']}/dispute", json={"reason": reason}
        ).status_code
        == 422
    )


def test_admin_metadata_and_student_responses_do_not_leak(workflow):
    d, _, conv = approved(workflow)
    body = "Contenido privado que el administrador no puede leer"
    call(
        workflow,
        "post",
        f"conversations/{conv}/messages",
        json={"body": body, "client_message_id": str(uuid4())},
    )
    admin = call(workflow, "get", f"admin/deliveries/{d['id']}", "admin")
    assert admin.status_code == 200
    assert admin.json()["message_count"] == 1 and body not in admin.text
    assert len(admin.json()["claim"]["match"]["factors"]) == 9
    assert (
        call(workflow, "get", f"conversations/{conv}/messages", "admin").status_code
        == 404
    )
    student = call(workflow, "get", "deliveries/me").json()

    def inspect(value):
        if isinstance(value, dict):
            assert not set(value) & {
                "email",
                "student_code",
                "password_hash",
                "user_id",
                "admin_id",
                "admin_note",
                "private_feature",
                "extracted_data",
                "storage_key",
            }
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(student)
    assert call(workflow, "get", "admin/deliveries").status_code == 403
    assert call(workflow, "get", "deliveries/me?limit=101").status_code == 422
    assert call(workflow, "get", "deliveries/me?status=wrong").status_code == 422
    assert (
        call(workflow, "get", "admin/deliveries?limit=1", "admin").json()["total"] == 1
    )


@pytest.mark.parametrize("state", ["pending", "approved", "rejected"])
def test_evidence_frozen_only_for_pending_and_approved_claim(workflow, state):
    claim = workflow.claim().json()
    if state == "approved":
        workflow.approve(claim["id"])
    elif state == "rejected":
        call(
            workflow,
            "post",
            f"admin/claims/{claim['id']}/reject",
            "admin",
            json={"rejection_reason": "No coincide la evidencia"},
        )
    expected = 200 if state == "rejected" else 409
    for report, actor in ((workflow.lost_id, "A"), (workflow.found_id, "B")):
        assert (
            call(
                workflow,
                "patch",
                f"reports/{report}",
                actor,
                json={"description": "Cambio posterior"},
            ).status_code
            == expected
        )
        if state != "rejected":
            assert (
                call(workflow, "delete", f"reports/{report}", actor).status_code == 409
            )
            assert (
                call(workflow, "delete", f"reports/{report}/image", actor).status_code
                == 409
            )


def test_approval_failure_rolls_back_delivery_and_conversation(workflow, monkeypatch):
    import app.infrastructure.database.delivery_repository as module

    claim = workflow.claim().json()

    def failure(*args):
        raise DBAPIError("controlled test failure", None, Exception())

    monkeypatch.setattr(module, "add_delivery", failure)
    assert workflow.approve(claim["id"]).status_code == 503
    with Session(workflow.engine) as s:
        assert s.scalar(select(func.count()).select_from(Delivery)) == 0
        assert s.scalar(select(func.count()).select_from(Conversation)) == 0
        assert s.get(OwnershipClaim, UUID(claim["id"])).status == "pending"


def test_concurrent_confirmations_and_complete_are_serialized(workflow):
    if workflow.engine.dialect.name != "postgresql":
        pytest.skip("Real PostgreSQL row locks required")
    d, _, _ = approved(workflow)
    with ThreadPoolExecutor(4) as pool:
        responses = list(
            pool.map(lambda actor: confirm(workflow, d, actor), ["A", "A", "B", "B"])
        )
    assert all(r.status_code == 200 for r in responses)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: complete(workflow, d), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with Session(workflow.engine) as s:
        assert s.scalar(select(func.count()).select_from(DeliveryEvent)) == 4
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE delivery_events SET note='altered'"))
        s.rollback()
        with pytest.raises(DBAPIError):
            s.execute(text("DELETE FROM delivery_events"))
        s.rollback()


def test_backfill_preserves_existing_approved_conversation(workflow):
    from alembic import command
    from alembic.config import Config

    d, claim, conversation = approved(workflow)
    with workflow.engine.begin() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        if workflow.engine.dialect.name == "sqlite":
            command.stamp(config, "head")
        command.downgrade(config, "0004_ownership_chat")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
    current = call(workflow, "get", f"conversations/{conversation}/delivery")
    assert current.status_code == 200
    assert current.json()["claim_id"] == claim
    assert current.json()["status"] == "coordinating"
    assert len(current.json()["events"]) == 1
    with Session(workflow.engine) as session:
        assert session.scalar(select(func.count()).select_from(Delivery)) == 1
        assert session.get(Conversation, UUID(conversation)).status == "active"


def test_closed_delivery_dispute_and_role_spoof_are_blocked(workflow):
    d, _, _ = approved(workflow)
    assert (
        call(
            workflow,
            "post",
            f"deliveries/{d['id']}/confirm",
            json={"role": "custodian"},
        ).status_code
        == 422
    )
    confirm(workflow, d)
    confirm(workflow, d, "B")
    complete(workflow, d)
    assert (
        call(
            workflow,
            "post",
            f"deliveries/{d['id']}/dispute",
            json={"reason": "No debe reabrir un cierre validado"},
        ).status_code
        == 409
    )


def test_rejected_claim_has_no_delivery(workflow):
    claim = workflow.claim().json()
    call(
        workflow,
        "post",
        f"admin/claims/{claim['id']}/reject",
        "admin",
        json={"rejection_reason": "No coincide"},
    )
    assert call(workflow, "get", "deliveries/me").json()["total"] == 0


@pytest.mark.parametrize("operation", ["patch", "delete", "image"])
def test_complete_retains_report_read_only(workflow, operation):
    d, _, _ = approved(workflow)
    confirm(workflow, d)
    confirm(workflow, d, "B")
    assert complete(workflow, d).status_code == 200
    path = f"reports/{workflow.lost_id}"
    if operation == "patch":
        response = call(workflow, "patch", path, json={"description": "No modificar"})
    elif operation == "delete":
        response = call(workflow, "delete", path)
    else:
        response = call(workflow, "delete", path + "/image")
    assert response.status_code == 409


def test_completion_rollback_preserves_reports_chat_and_events(workflow, monkeypatch):
    from app.infrastructure.database.delivery_repository import (
        SQLAlchemyDeliveryRepository,
    )

    d, _, conversation = approved(workflow)
    confirm(workflow, d)
    confirm(workflow, d, "B")
    original = SQLAlchemyDeliveryRepository.save

    def failure(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise DBAPIError("controlled rollback", None, Exception())

    monkeypatch.setattr(SQLAlchemyDeliveryRepository, "save", failure)
    assert complete(workflow, d).status_code == 503
    with Session(workflow.engine) as session:
        assert session.get(Delivery, UUID(d["id"])).status == "awaiting_admin"
        assert session.get(ObjectReport, workflow.lost_id).status == "active"
        assert session.get(ObjectReport, workflow.found_id).status == "active"
        assert session.get(Conversation, UUID(conversation)).status == "active"
        assert session.scalar(select(func.count()).select_from(DeliveryEvent)) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "completed"},
        {"status": "awaiting_admin"},
        {"status": "awaiting_confirmations"},
        {"status": "disputed"},
        {"admin_note": "x" * 2001},
    ],
)
def test_delivery_database_constraints(workflow, changes):
    d, _, _ = approved(workflow)
    with Session(workflow.engine) as session:
        row = session.get(Delivery, UUID(d["id"]))
        for key, value in changes.items():
            setattr(row, key, value)
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()


def test_frozen_photo_put_and_permission_flag(workflow):
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (20, 20)).save(image, "PNG")
    path = f"reports/{workflow.lost_id}"
    assert not call(workflow, "get", path).json()["evidence_locked"]
    workflow.claim()
    assert call(workflow, "get", path).json()["evidence_locked"]
    assert (
        call(
            workflow,
            "put",
            path + "/image",
            files={"image": ("photo.png", image.getvalue(), "image/png")},
        ).status_code
        == 409
    )
